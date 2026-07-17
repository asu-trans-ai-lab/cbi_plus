# -*- coding:utf-8 -*-
"""QVDF turn-key pipeline — orchestrator (logging, period split, tables, figures)."""
import os, logging
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import config as C
import qvdf_core as Q


def _logger(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    log = logging.getLogger(out_dir)
    log.setLevel(logging.DEBUG); log.handlers.clear()
    fh = logging.FileHandler(os.path.join(out_dir, "run.log"), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG); fh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    ch = logging.StreamHandler(); ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(fh); log.addHandler(ch)
    return log


def run_corridor(key):
    cfg = C.CORRIDORS[key]
    out = os.path.join(C.OUT_ROOT, key)
    log = _logger(out)
    log.info(f"\n================ {cfg['name']}  [{key}] ================")

    # -- Step 1: load + aggregate to DT_MIN bins ----------------------------
    try:
        df, mode = Q.load_corridor(cfg, log)
    except Exception as e:
        log.error(f"  FATAL load error: {e}"); return
    df = df.dropna(subset=["speed", "date", "link_id"])
    df["bin"] = (df.t_min // C.DT_MIN) * C.DT_MIN
    agg = {"speed": "mean", "weekday": "first", "lanes": "first", "length": "first"}
    if mode == "measured":
        agg["flow_pl"] = "mean"
    a = df.groupby(["link_id", "date", "bin"], as_index=False).agg(agg).rename(columns={"bin": "t_min"})
    log.info(f"  Step 1: {a.link_id.nunique()} links, {a.date.nunique()} dates, "
             f"{len(a):,} link-interval rows ({mode})")

    # -- Step 2: S3 fundamental diagram per link -> Table 5 -----------------
    vf = cfg["free_flow"]; capp = cfg["capacity_prior"]
    fdp, s3_rows = {}, []
    for lid, g in a.groupby("link_id"):
        if mode == "speed_only":
            m = 4.0; uc = vf / 2 ** (2 / m); cap = capp; kc = cap / uc
            fdp[lid] = dict(vf=vf, kc=kc, m=m, uc=uc, cap=cap, source="inrix_prior")
            g2 = g.copy(); g2["flow_pl"] = Q.inverse_s3_flow(g2.speed.to_numpy(), vf, kc, m)
            a.loc[g2.index, "flow_pl"] = g2["flow_pl"]
        else:
            fdp[lid] = Q.fit_s3(g, vf, capp, log)
        p = fdp[lid]
        # FD fit R2 (speed vs S3-predicted at observed density) -- Stage-0 quality
        r2 = ""
        if mode == "measured" and "flow_pl" in g.columns:
            gg = g[(g.speed > 0) & (g.flow_pl > 0)].copy(); gg["k"] = gg.flow_pl / gg.speed
            gg = gg[(gg.k >= 1) & (gg.k < 220)]
            if len(gg) >= 30:
                pred = Q.s3_speed(gg.k.to_numpy(), p["vf"], p["kc"], p["m"])
                obs = gg.speed.to_numpy(); sst = float(np.sum((obs - obs.mean()) ** 2))
                r2 = round(float(1 - np.sum((obs - pred) ** 2) / sst), 3) if sst > 0 else ""
        # THREE speed concepts (per the NVTA slides 54-56): posted free-flow, observed 99th-pct
        # (free-flow proxy), and the CRITICAL speed (= cut-off) that drives the whole congestion id.
        spd99 = round(float(g.speed.quantile(0.99)), 1) if g.speed.notna().any() else ""
        crit = round(C.CUTOFF_RATIO * p["vf"], 1)
        s3_rows.append([lid, round(p["cap"], 1), round(p["uc"], 1), round(p["kc"], 1),
                        round(p["vf"], 1), spd99, crit, round(p["m"], 2), p["source"], r2])
    pd.DataFrame(s3_rows, columns=["link_id", "capacity", "speed_at_capacity_uc", "critical_density_kc",
                                   "free_flow_speed_posted", "free_flow_speed_obs_99pct",
                                   "critical_speed_cutoff", "m", "fd_source", "fd_fit_R2"]).to_csv(
        os.path.join(out, "Stage0_FD.csv"), index=False)
    nfit = sum(1 for p in fdp.values() if p["source"] == "fit")
    log.info(f"  Stage 0 (FD calibration): Stage0_FD.csv for {len(fdp)} links "
             f"({nfit} fitted, {len(fdp)-nfit} prior/inrix)")

    # -- Build the weekday-average profile(s) -------------------------------
    # wd_mode "avg_weekday": ONE Mon-Fri average profile per link (no day-by-day) -> QVDF
    #   calibrated across the corridor's links.
    # wd_mode "per_dow": one profile per day-of-week -> QVDF calibrated per link across dow (paper).
    wd_mode = cfg.get("wd_mode", "per_dow")
    wcols = {"speed": "mean", "length": "first", "lanes": "first"}
    if "flow_pl" in a.columns:
        wcols["flow_pl"] = "mean"
    if wd_mode == "avg_weekday":
        aw = a[a.weekday < 5]                               # Mon-Fri only
        wda = aw.groupby(["link_id", "t_min"], as_index=False).agg(wcols)
        wda["weekday"] = 0; wda["date"] = "Weekday"
        log.info(f"  Average-weekday profile (Mon-Fri): {wda.link_id.nunique()} links x 1 profile "
                 f"-> corridor-level calibration across links")
    else:
        wda = a.groupby(["link_id", "weekday", "t_min"], as_index=False).agg(wcols)
        wda["date"] = wda["weekday"].map(C.WEEKDAY_NAME)
        log.info(f"  Weekday-average profiles: {wda.link_id.nunique()} links x up to 7 day-of-week "
                 f"-> per-link calibration")

    # -- Step 3: detect episodes on each weekday-average profile (period-tagged) --
    all_eps = []
    for lid, g in wda.groupby("link_id"):
        if lid not in fdp:
            continue
        all_eps += Q.paq_episodes(g, fdp[lid], C.CUTOFF_RATIO * fdp[lid]["vf"])
    ep = pd.DataFrame(all_eps)
    if len(ep) == 0:
        log.warning("  no episodes detected"); return
    ep.to_csv(os.path.join(out, "daily_paq_all.csv"), index=False)
    log.info(f"  Step 3: {len(ep)} episode/day rows; congested by period: "
             + ", ".join(f"{p}={int(((ep.period==p)&(ep.P>0)).sum())}" for p in C.PERIODS))

    # -- Step 4-6: per assignment period ------------------------------------
    t6_all, t7_all, t8_all = [], [], []
    params_by_period = {}
    for per, win in C.PERIODS.items():
        day = ep[ep.period == per].copy()
        if len(day) == 0:
            continue
        log.info(f"  --- period {per} {win[0]//60:02d}:00-{win[1]//60:02d}:00 ---")

        # Step 4: Table 6 congestion stats (count distinct dates)
        for lid, g in day.groupby("link_id"):
            nd = g.date.nunique(); npos = g.loc[g.P > 0, "date"].nunique()
            t6_all.append([lid, per, nd, npos, round(npos/nd*100) if nd else 0,
                           round(g.loc[g.P > 0, "P"].mean(), 2) if npos else 0])

        # Step 5: calibrate -> Table 7 (loose [0,10] box on f_p/s; per-link V_t2 error reported)
        prm = {}
        if wd_mode == "avg_weekday":
            scope = "corridor"
            c = Q.calibrate_link(day, C.CUTOFF_RATIO * cfg["free_flow"], log)
            if c is None:
                if (day.P > 0).sum() == 0:
                    continue
                # congestion exists but no D/C-P variation to fit (uniformly gridlocked corridor):
                # use the transferred default so the corridor still gets QVDF params + a hand-off.
                d = dict(C.DEFAULT_QVDF); d["alpha"] = (8/15) * d["f_p"] * d["f_d"] ** d["s"]
                d["beta"] = d["n"] * d["s"]; d["n_cong"] = int((day.P > 0).sum())
                d["reliability"] = "default"; d["shrunk"] = False; c = d
                log.warning(f"    {per}: cannot self-calibrate (no D/C-P variation) -> transferred default")
            c["shrunk"] = False
            for lid in day.link_id.unique():
                prm[lid] = c                                # every link uses the corridor params
            log.info(f"    Step 5: CORRIDOR calibration across {c['n_cong']} congested links "
                     f"({c['reliability']}): f_d={c['f_d']:.2f} n={c['n']:.2f} "
                     f"f_p={c['f_p']:.3f} s={c['s']:.2f}")
        else:
            scope = "link"
            for lid, g in day.groupby("link_id"):
                cc = Q.calibrate_link(g, C.CUTOFF_RATIO * fdp[lid]["vf"], log)
                if cc is not None:
                    prm[lid] = cc
            if not prm:
                log.warning(f"    no calibratable links in {per}"); continue
            prm = Q.shrink_params(prm, log)
            rc = pd.Series([p["reliability"] for p in prm.values()]).value_counts()
            log.info(f"    Step 5: calibrated {len(prm)} links "
                     f"({rc.get('high',0)} high / {rc.get('medium',0)} med / {rc.get('low',0)} low)")
        # per-link Table 7 rows incl. modeled-vs-observed V_t2 (the residual diagnostic)
        for lid, p in prm.items():
            g = day[(day.link_id == lid) & (day.P > 0)]
            if len(g) == 0:
                continue
            cut = C.CUTOFF_RATIO * fdp[lid]["vf"]
            P_link = float(g.P.mean()); vt2_obs = float(g.v_t2.mean())
            vt2_mod = Q.predict_vt2(cut, p["f_p"], p["s"], P_link)
            err = vt2_mod - vt2_obs
            t7_all.append([lid, per, scope, round(p["f_d"], 4), round(p["n"], 4), round(p["f_p"], 4),
                           round(p["s"], 4), round(p["alpha"], 4), round(p["beta"], 4),
                           p["n_cong"], p["reliability"], p.get("shrunk", False),
                           round(vt2_obs, 1), round(vt2_mod, 1), round(err, 1),
                           round(err / max(vt2_obs, 1.0) * 100, 1)])

        # Step 6: Table 8 gamma (per link x weekday)
        for lid in prm:
            g = day[day.link_id == lid]; p = prm[lid]; fp = fdp[lid]
            uc = fp["uc"]; cap = fp["cap"]; L = g.length.iloc[0]; cut = C.CUTOFF_RATIO * fp["vf"]
            for w in range(7):
                gw = g[(g.weekday == w) & (g.P > 0)]
                if len(gw) == 0:
                    continue
                dcm = gw.DC.mean(); mu = min(gw.demand.mean() / max(gw.P.mean(), 0.01), cap)
                Pest = p["f_d"] * dcm ** p["n"]
                vt2 = cut / (1 + p["f_p"] * Pest ** p["s"]); vbar = cut / (1 + p["alpha"] * dcm ** p["beta"])
                wlab = "Weekday" if wd_mode == "avg_weekday" else C.WEEKDAY_NAME[w]
                t8_all.append([lid, per, wlab, round(dcm, 2), round(Pest, 2),
                               round(vt2, 2), round(vbar, 2), round(float(Q.gamma_of(p, dcm, mu, L, uc)), 2)])

        params_by_period[per] = prm
        _figures(key, cfg, per, win, a, wda, day, prm, fdp, out, log)

    # -- avg-weekday congestion-episode figure, ONE PANEL PER LINK ----------
    # (built for every corridor, incl. I-10's 4 detectors, from the Mon-Fri average profile)
    awcols = {"speed": "mean", "length": "first", "lanes": "first"}
    if "flow_pl" in a.columns:
        awcols["flow_pl"] = "mean"
    awk = a[a.weekday < 5].groupby(["link_id", "t_min"], as_index=False).agg(awcols)
    awk["weekday"] = 0; awk["date"] = "Weekday"
    # export the AVERAGE-WEEKDAY DATA (Mon-Fri mean per link x 15-min) — the Stage-I calibration input
    # AND the small, self-contained representative dataset (bundled for the package self-demo).
    acols = (["link_id", "t_min", "speed", "length", "lanes"]
             + (["flow_pl"] if "flow_pl" in awk.columns else []))
    awk[[c for c in acols if c in awk.columns]].rename(
        columns={"speed": "avg_weekday_speed_mph", "flow_pl": "avg_weekday_flow_veh_per_hr_lane",
                 "length": "length_mi"}).to_csv(os.path.join(out, "avgweekday_profile.csv"), index=False)
    epw = []                                               # avg-weekday episodes (with D/C)
    for lid, g in awk.groupby("link_id"):
        if lid in fdp:
            epw += Q.paq_episodes(g, fdp[lid], C.CUTOFF_RATIO * fdp[lid]["vf"])
    epw = pd.DataFrame(epw)
    # Calibrate f_d/n/f_p/s on THESE avg-weekday episodes (corridor across links) so the figure's
    # modeled V_t2 = cut-off/(1+f_p*P^s) is consistent with the same episodes it is drawn on.
    epw_params = {}
    if len(epw):
        for per in C.PERIODS:
            dper = epw[epw.period == per]
            if (dper.P > 0).sum() == 0:
                continue
            c = Q.calibrate_link(dper, C.CUTOFF_RATIO * cfg["free_flow"], log)
            if c is None:                                  # gridlocked -> transferred default
                c = dict(C.DEFAULT_QVDF)
                c["alpha"] = (8/15) * c["f_p"] * c["f_d"] ** c["s"]; c["beta"] = c["n"] * c["s"]
            epw_params[per] = {lid: c for lid in dper.link_id.unique()}
    _episode_grid(cfg, a, awk, epw, epw_params, fdp, out, log)

    # -- Stage-I quality measures + gates (AVERAGE-WEEKDAY calibration only) -------
    # Day-to-day variation / day-by-day QVDF is NOT a first-stage gate -- it belongs to Stage II
    # (time-dependent ODME + day-by-day calibration), so it is written separately below.
    import quality as QQ
    cal_q = QQ.calibration_quality(ep, params_by_period, fdp, cfg)
    ts_q = QQ.timeseries_quality(a, awk, fdp)
    fd_r2 = QQ.fd_fit_r2(a, fdp, mode)
    gq = QQ.gates(cal_q, ts_q, fd_r2, mode)
    cal_q.to_csv(os.path.join(out, "Quality_calibration.csv"), index=False)
    ts_q[["link_id", "n_weekdays", "smooth_vs_raw_R2", "smooth_vs_raw_RMSE"]].to_csv(
        os.path.join(out, "Quality_timeseries.csv"), index=False)            # Stage I: smoothing fidelity
    ts_q[["link_id", "n_weekdays", "day2day_RMSE_mph", "day2day_R2", "day2day_CV"]].to_csv(
        os.path.join(out, "StageII_day2day_variation.csv"), index=False)     # Stage II prep
    gq.to_csv(os.path.join(out, "quality_gates.csv"), index=False)
    if len(gq):
        npass = (gq.status == "PASS").sum()
        log.info(f"  Stage-I quality gates: {npass}/{len(gq)} PASS  | "
                 + " ".join(f"{p}:{(gq[(gq.period==p)].status=='PASS').sum()}/"
                            f"{len(gq[gq.period==p])}" for p in gq.period.unique()))
        for _, r in cal_q.iterrows():
            log.info(f"    {r.period}: D/C->P R2={r.step1_DC_P_R2} P->mag R2={r.step2_P_mag_R2} "
                     f"| P MAPE={r.P_MAPE_pct}% vt2 MAPE={r.vt2_MAPE_pct}% t0 MAE={r.t0_MAE_min}min")
        if len(ts_q):
            log.info(f"    smoothing R2 median={ts_q.smooth_vs_raw_R2.median():.3f} "
                     f"(Stage-II day-to-day variation -> StageII_day2day_variation.csv)")

    # -- Stage hand-off (time-dependent avg-weekday: raw/smoothed/model speed + counts + emissions)
    import handoff as H
    hdf = H.build_handoff(cfg, a, awk, epw, epw_params, fdp, mode, out)
    log.info(f"  Hand-off: handoff_avgweekday_timedependent.csv "
             f"({len(hdf)} link x 15-min rows) + handoff_link_qvdf_params.csv "
             f"-> Stage II ODME / Stage III emissions")

    # -- write combined tables ---------------------------------------------
    pd.DataFrame(t6_all, columns=["link_id", "period", "valid_days", "days_P>0", "pct_congested",
                                  "avg_P_h"]).to_csv(os.path.join(out, "Table6_congestion_stats.csv"), index=False)
    pd.DataFrame(t7_all, columns=["link_id", "period", "calib_scope", "f_d", "n", "f_p", "s",
                                  "alpha", "beta", "n_congested_days", "reliability", "shrunk",
                                  "v_t2_obs", "v_t2_model", "v_t2_err_mph", "v_t2_err_pct"]).to_csv(
        os.path.join(out, "Table7_calibrated.csv"), index=False)
    pd.DataFrame(t8_all, columns=["link_id", "period", "weekday", "mean_DC", "mean_P", "mean_v_t2",
                                  "mean_v_bar", "gamma"]).to_csv(os.path.join(out, "Table8_gamma.csv"), index=False)
    log.info(f"  DONE -> Tables 5-8 + figures in {out}")
    for h in log.handlers:
        h.close()


def _figures(key, cfg, per, win, a, wda, day, prm, fdp, out, log):
    fig = os.path.join(out, "figures"); os.makedirs(fig, exist_ok=True)
    dets = sorted(prm, key=lambda l: -prm[l]["n_cong"])[:4]
    if not dets:
        return
    # Fig 8 FD (once, period-independent) — only on first period
    if per == list(C.PERIODS)[0]:
        f, ax = plt.subplots(2, 2, figsize=(11, 8))
        for x, lid in zip(ax.flat, dets):
            g = a[a.link_id == lid]; p = fdp[lid]
            if "flow_pl" in g and g.flow_pl.notna().any():
                x.scatter(g.flow_pl, g.speed, s=3, c="k", alpha=0.2)
            kk = np.linspace(0.1, 200, 300); x.plot(kk * Q.s3_speed(kk, p["vf"], p["kc"], p["m"]),
                                                    Q.s3_speed(kk, p["vf"], p["kc"], p["m"]), "b--", lw=1.6)
            x.set_xlim(0, 2400); x.set_ylim(0, 85)
            x.set_title(f"ID {lid}  vf={p['vf']:.0f} uc={p['uc']:.0f} cap={p['cap']:.0f} ({p['source']})", fontsize=8)
            x.set_xlabel("Volume (veh/h/lane)"); x.set_ylabel("Speed (mph)")
        f.suptitle(f"Fig 8 {cfg['name']} — volume-speed FD"); f.tight_layout()
        f.savefig(os.path.join(fig, "Fig8_FD.png"), dpi=130); plt.close(f)

    cong = day[day.P > 0]
    # Fig 9 distributions
    f, ax = plt.subplots(2, 2, figsize=(11, 8))
    for x, (col, xl) in zip(ax.flat, [("P", "Congestion duration (h)"), ("demand", "Inflow demand (veh/lane)"),
                                      ("DC", "D/C ratio"), ("qdf", "QDF")]):
        v = cong[col].dropna()
        if len(v):
            x.hist(v, bins=12, color="white", edgecolor="black", weights=np.ones(len(v))/len(v))
            x.set_xlabel(f"{xl}\nMean = {v.mean():.2f}")
        x.set_ylabel("Frequency")
    f.suptitle(f"Fig 9 {cfg['name']} {per} — distributions"); f.tight_layout()
    f.savefig(os.path.join(fig, f"Fig9_distributions_{per}.png"), dpi=130); plt.close(f)

    # Fig 10/11/12 calibration
    for figno, (xc, yc, ttl) in {10: ("DC", "P", "D/C vs P"), 11: ("P", "magnitude", "P vs magnitude"),
                                 12: ("DC", "cd_mean_speed", "D/C vs avg speed")}.items():
        f, ax = plt.subplots(2, 2, figsize=(11, 8))
        for x, lid in zip(ax.flat, dets):
            g = day[(day.link_id == lid) & (day.P > 0)]; p = prm[lid]
            if len(g) == 0:
                continue
            x.scatter(g[xc], g[yc], s=8, c="k")
            xr = np.linspace(0.01, max(g[xc].max(), 0.1), 100)
            if figno == 10:
                x.plot(xr, p["f_d"] * xr ** p["n"], "b--", lw=1.6)
            elif figno == 11:
                x.plot(xr, p["f_p"] * xr ** p["s"], "b--", lw=1.6)
            else:
                cut = C.CUTOFF_RATIO * fdp[lid]["vf"]; x.plot(xr, cut / (1 + p["alpha"] * xr ** p["beta"]), "b--", lw=1.6)
            x.set_title(f"ID {lid} ({p['reliability']})", fontsize=9); x.set_xlabel(xc); x.set_ylabel(yc)
        f.suptitle(f"Fig {figno} {cfg['name']} {per} — {ttl}"); f.tight_layout()
        f.savefig(os.path.join(fig, f"Fig{figno}_{xc}_{yc}_{per}.png"), dpi=130); plt.close(f)

    # Fig 14-17 observed-vs-QVDF speed profile.
    #   avg_weekday -> the avg-weekday profile of the top 4 congested LINKS
    #   per_dow     -> the top link across Mon-Thu
    wd_mode = cfg.get("wd_mode", "per_dow")
    panels = [(l, 0) for l in dets[:4]] if wd_mode == "avg_weekday" else [(dets[0], w) for w in range(4)]
    for i, (lid, w) in enumerate(panels):
        p = prm[lid]; fp = fdp[lid]; vf = fp["vf"]
        gw = day[(day.link_id == lid) & (day.weekday == w) & (day.P > 0)]
        if len(gw) == 0:
            continue
        t0m, t3m = gw.t0.mean(), gw.t3.mean(); vt2m = gw.v_t2.mean(); t2m = gw.t2.mean()
        pw = (int(max(C.WIDE_WINDOW[0], t0m * 60 - 75)), int(min(C.WIDE_WINDOW[1], t3m * 60 + 75)))
        vt2_pred = Q.predict_vt2(C.CUTOFF_RATIO * vf, p["f_p"], p["s"], t3m - t0m)
        ts, ve = Q.td_speed_shape(t0m, t2m, t3m, vt2_pred, C.CUTOFF_RATIO * vf, vf, pw)
        ob = wda[(wda.link_id == lid) & (wda.weekday == w) & (wda.t_min >= pw[0]) & (wda.t_min < pw[1])
                 ].groupby("t_min").speed.mean()
        lbl = "avg weekday" if wd_mode == "avg_weekday" else C.WEEKDAY_NAME[w]
        f, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(ob.index / 60.0, ob.values, "r--s", ms=3, label=f"Observed ({lbl})")
        ax.plot(ts, ve, "k-o", ms=3, label="Estimated QVDF")
        ax.axhline(C.CUTOFF_RATIO * vf, color="green", ls="--", lw=1, label=f"cut-off {C.CUTOFF_RATIO*vf:.0f}")
        ax.axvline(t0m, color="gray", ls=":", lw=1); ax.axvline(t3m, color="gray", ls=":", lw=1)
        ax.set_xlim(pw[0]/60, pw[1]/60); ax.set_ylim(0, 80); ax.set_ylabel("Mean speed (mph)")
        ax.set_title(f"Fig {14+i} {cfg['name']} {per} — obs vs QVDF, ID {lid}, {lbl}", fontsize=10)
        ax.legend(fontsize=8); ax.grid(alpha=0.3); f.tight_layout()
        tag = str(lid) if wd_mode == "avg_weekday" else C.WEEKDAY_NAME[w]
        f.savefig(os.path.join(fig, f"Fig{14+i}_td_{per}_{tag}.png"), dpi=130); plt.close(f)

    # --- t0/t2/t3 identification diagnostic (engineering-judgement check) ---
    _diag_windows(cfg, per, win, wda, day, fdp, dets, fig)


def _paginate(figd, per, links, rows, draw_fn, prefix, suptitle):
    """grid layout + pagination shared by the two per-link figures; draw_fn(axx, lid, row, first)."""
    import math
    ppg = 20
    for pg in range(0, len(links), ppg):
        chunk = links[pg:pg + ppg]
        ncol = min(4, len(chunk)); nrow = math.ceil(len(chunk) / ncol)
        f, ax = plt.subplots(nrow, ncol, figsize=(3.7 * ncol, 2.5 * nrow), squeeze=False)
        axes = list(ax.flat)
        for j, lid in enumerate(chunk):
            draw_fn(axes[j], lid, rows[lid], j == 0)
        for axx in axes[len(chunk):]:
            axx.axis("off")
        f.suptitle(suptitle, fontsize=11); f.tight_layout()
        sfx = "" if len(links) <= ppg else f"_p{pg//ppg+1}"
        f.savefig(os.path.join(figd, f"{prefix}_{per}{sfx}.png"), dpi=130); plt.close(f)


def _episode_grid(cfg, a, awk, epw, epw_params, fdp, out, log):
    """TWO per-link figures per corridor x period:
       (1) RAW_vs_AVGWEEKDAY  -- every weekday day's raw 15-min trace + the average-weekday profile
       (2) AVGWEEKDAY_vs_QVDF -- the average-weekday observed profile + the QVDF model curve
    For I-10 the panels are the 4 detectors; for corridors, every congested link."""
    figd = os.path.join(out, "figures"); os.makedirs(figd, exist_ok=True)
    if len(epw) == 0:
        return

    def _win(r):
        return (int(max(C.WIDE_WINDOW[0], r.t0 * 60 - 75)), int(min(C.WIDE_WINDOW[1], r.t3 * 60 + 75)))

    for per in C.PERIODS:
        ec = epw[(epw.period == per) & (epw.P > 0)].copy()
        if len(ec) == 0:
            continue
        ec = ec.sort_values("P", ascending=False).drop_duplicates("link_id")
        links = ec.link_id.tolist()
        rows = {lid: ec[ec.link_id == lid].iloc[0] for lid in links}

        # ---- Figure 1: raw daily data vs average weekday ----
        def draw_raw(axx, lid, r, first):
            cut = C.CUTOFF_RATIO * fdp[lid]["vf"]; pw = _win(r)
            sub = a[(a.link_id == lid) & (a.weekday < 5) & (a.t_min >= pw[0]) & (a.t_min < pw[1])]
            for d, (_, gd) in enumerate(sub.groupby("date")):
                gd = gd.sort_values("t_min")
                axx.plot(gd.t_min / 60.0, gd.speed, color="0.7", lw=0.5, alpha=0.5,
                         label="raw daily (weekdays)" if (first and d == 0) else None)
            av = awk[(awk.link_id == lid) & (awk.t_min >= pw[0]) & (awk.t_min < pw[1])].sort_values("t_min")
            axx.plot(av.t_min / 60.0, av.speed, color="tab:blue", lw=2.2,
                     label="average weekday" if first else None)
            axx.axhline(cut, color="green", ls="--", lw=1, label="cut-off" if first else None)
            axx.set_xlim(pw[0] / 60, pw[1] / 60); axx.set_ylim(0, 80)
            axx.set_title(f"link {lid}: P={r.P:.1f}h vt2={r.v_t2:.0f}", fontsize=8); axx.tick_params(labelsize=6)
            if first:
                axx.legend(fontsize=6, loc="lower right")

        # ---- Figure 2: average weekday vs QVDF model ----
        def draw_qvdf(axx, lid, r, first):
            fp = fdp[lid]; cut = C.CUTOFF_RATIO * fp["vf"]; vf = fp["vf"]; pw = _win(r)
            av = awk[(awk.link_id == lid) & (awk.t_min >= pw[0]) & (awk.t_min < pw[1])].sort_values("t_min")
            axx.plot(av.t_min / 60.0, av.speed.to_numpy(), color="tab:blue", lw=1.6, marker=".", ms=2,
                     label="average weekday (obs)" if first else None)
            pp = epw_params.get(per, {}).get(lid)
            if pp is not None:
                # MODEL V_t2 = v_co/(1+f_p P^s) at the OBSERVED trough TIME t2. The V_t2 quality gate
                # decides whether this link is QVDF-modelable: if the corridor model is within
                # tolerance and D/C is not censored -> solid model curve (black); otherwise it is an
                # all-day-saturated link the single-peak QVDF cannot fit -> show the queue shape at the
                # observed depth in GRAY (flagged, not a misleading deep model trough).
                vt2_pred = Q.predict_vt2(cut, pp["f_p"], pp["s"], r.t3 - r.t0)
                censored = r.DC >= C.DOC_MAX - 0.01
                good = (abs(vt2_pred - r.v_t2) <= C.VT2_TOL_MPH) and not censored
                vt2_use = vt2_pred if good else r.v_t2
                ts, ve = Q.td_speed_shape(r.t0, r.t2, r.t3, vt2_use, cut, vf, pw)
                if good:
                    axx.plot(ts, ve, "k-", lw=1.8, label="QVDF model" if first else None)
                    axx.plot(r.t2, vt2_pred, "k^", ms=6, label="modeled V_t2" if first else None)
                else:
                    axx.plot(ts, ve, color="0.55", lw=1.6, ls="--",
                             label="QVDF (saturated link)" if first else None)
                    axx.text(0.5, 0.04, "saturated", transform=axx.transAxes, ha="center",
                             fontsize=6, color="0.4")
                axx.plot(r.t2, r.v_t2, "rx", ms=6, mew=1.5, label="observed V_t2" if first else None)
            axx.axhline(cut, color="green", ls="--", lw=1, label="cut-off" if first else None)
            for tt, cc in [(r.t0, "gray"), (r.t2, "red"), (r.t3, "gray")]:
                axx.axvline(tt, color=cc, ls=":", lw=1)
            axx.axvspan(r.t0, r.t3, color="orange", alpha=0.10)
            axx.set_xlim(pw[0] / 60, pw[1] / 60); axx.set_ylim(0, 80)
            axx.set_title(f"link {lid}: D/C={r.DC:.1f} P={r.P:.1f}h vt2={r.v_t2:.0f}", fontsize=8)
            axx.tick_params(labelsize=6)
            if first:
                axx.legend(fontsize=6, loc="lower right")

        _paginate(figd, per, links, rows, draw_raw, "RAW_vs_AVGWEEKDAY",
                  f"{cfg['name']} {per} — raw daily data vs average weekday (per link)")
        _paginate(figd, per, links, rows, draw_qvdf, "AVGWEEKDAY_vs_QVDF",
                  f"{cfg['name']} {per} — average weekday vs QVDF model (per link)")
    log.info("  per-link figures (raw-vs-avg + avg-vs-QVDF): " + ", ".join(
        f"{p}={epw[(epw.period==p)&(epw.P>0)].link_id.nunique()}" for p in C.PERIODS))


def _diag_windows(cfg, per, win, wda, day, fdp, dets, fig):
    """Plot the smoothed weekday-average speed profile with the cut-off line and the identified
    t0/t2/t3, so the congestion duration can be checked against engineering judgement (t3 should
    return cleanly to the cut-off). avg_weekday -> top 4 LINKS; per_dow -> top link's worst days."""
    wd_mode = cfg.get("wd_mode", "per_dow")
    if wd_mode == "avg_weekday":
        # 4 links with the DEEPEST dip (lowest V_t2) in THIS period -- clearest t0/t2/t3, no empties
        cong = (day[day.P > 0].sort_values("v_t2").drop_duplicates("link_id").head(4))
        panels = [(r.link_id, r) for _, r in cong.iterrows()]
        title = "deepest-dip links"
    else:
        lid0 = dets[0]
        cong = day[(day.link_id == lid0) & (day.P > 0)].sort_values("P", ascending=False).head(4)
        panels = [(lid0, r) for _, r in cong.iterrows()]
        title = f"link {lid0}"
    if not panels:
        return
    npn = len(panels)                                      # size the grid to the panels (no empties)
    ncol = 1 if npn == 1 else 2
    nrow = int(np.ceil(npn / ncol))
    f, ax = plt.subplots(nrow, ncol, figsize=(6 * ncol, 4 * nrow), squeeze=False)
    axes = list(ax.flat)
    for x in axes[npn:]:
        x.axis("off")
    ww = C.WIDE_WINDOW
    for x, (lid, r) in zip(axes, panels):
        cut = C.CUTOFF_RATIO * fdp[lid]["vf"]
        gd = wda[(wda.link_id == lid) & (wda.date == r.date) & (wda.t_min >= ww[0]) & (wda.t_min < ww[1])].sort_values("t_min")
        if len(gd) < 4:
            continue
        tmh = gd.t_min.to_numpy() / 60.0
        sm = Q.smooth_speed(gd.speed.to_numpy())
        x.plot(tmh, gd.speed.to_numpy(), color="0.7", lw=1, marker=".", ms=3, label="observed 15-min")
        x.plot(tmh, sm, "b-", lw=2, label="smoothed")
        x.axhline(cut, color="green", ls="--", lw=1.2, label=f"cut-off {cut:.0f} mph")
        for tt, cc, nm in [(r.t0, "gray", "t0"), (r.t2, "red", "t2"), (r.t3, "gray", "t3")]:
            x.axvline(tt, color=cc, ls=":", lw=1.4)
            x.text(tt, 3, nm, color=cc, fontsize=8, ha="center")
        x.axvspan(r.t0, r.t3, color="orange", alpha=0.12)
        x.set_xlim(ww[0] / 60, ww[1] / 60); x.set_ylim(0, max(80, gd.speed.max() * 1.1))
        head = f"link {lid}" if wd_mode == "avg_weekday" else str(r.date)
        x.set_title(f"{head} [{r.period}]  P={r.P:.2f} h  t0={r.t0:.1f} t3={r.t3:.1f}", fontsize=9)
        x.set_xlabel("hour"); x.set_ylabel("speed (mph)"); x.legend(fontsize=7, loc="lower right")
    f.suptitle(f"t0/t2/t3 identification — {cfg['name']} {per}, {title} "
               f"(sustained +-{C.HYST_MIN}min crossing)", fontsize=11)
    f.tight_layout(); f.savefig(os.path.join(fig, f"DIAG_t0t3_{per}.png"), dpi=130); plt.close(f)
