# -*- coding:utf-8 -*-
"""QVDF turn-key — Stage hand-off package.

Writes, per data set, the TIME-DEPENDENT average-weekday product that feeds the next stages:
  handoff_avgweekday_timedependent.csv  (one row per link x 15-min bin):
     link_id, from_node_id, to_node_id, t_min, period,
     speed_raw, speed_smoothed, speed_qvdf_model,                 <- raw / smoothed / model speed
     count_per_lane_15min, lanes, count_total_15min,              <- Stage II time-dependent link COUNT
     length_mi, free_flow, cutoff, capacity_vphpl,
     vmt, emis_co2_g_obs, emis_co2_g_model                        <- Stage III emissions
  handoff_link_qvdf_params.csv          (one row per link): the calibrated QVDF parameters
     (f_d, n, f_p, s, alpha, beta, u_c, capacity) -> Stage II VDF / Stage III emission cost.

Stage II  (time-dependent ODME): uses count_total_15min + speed per 15 min (or 5 min) as the
          measurement vector per link; QVDF params give the VDF.
Stage III (QVDF emissions): uses speed_qvdf_model + count + the VSP/OpMode emission chain in
          QVDF_Part2_Emission_Derivations.tex. The CO2 columns here are a transparent steady-state
          placeholder (Barth-style speed U-curve) to be replaced by that chain.
"""
import os
import numpy as np
import pandas as pd
import config as C
import qvdf_core as Q

CO2_G_PER_GAL = 8887.0          # gasoline


def co2_g_per_mile(v):
    """transparent steady-state fuel U-curve (gal/mi) -> CO2 g/mi; placeholder for the QVDF-E
    VSP/OpMode chain. Minimum near ~50 mph, higher in congestion and at very high speed."""
    v = np.clip(np.asarray(v, float), 3.0, 80.0)
    fuel_gpm = np.clip(0.080 - 0.0022 * v + 0.0000235 * v ** 2, 0.02, 0.20)
    return fuel_gpm * CO2_G_PER_GAL


def add_conserved_flow(df, fdp, log=None, form="s3"):
    """Meso flow from the QVDF time-dependent speed, with corridor-regularized
    demand conservation. Per (link, period) congestion episode, back-compute the
    flow from the model speed via the S3-shape FD, using a SINGLE corridor density
    scale theta_bar (FD params NOT varied link-by-link) and a small per-link slack
    lambda so that sum_t q_i(t)*dt = the OBSERVED episode demand D_i exactly.
    Adds columns: q_qvdf_perlane, count_total_qvdf (conserved), theta_corridor,
    lambda_link, dev_frac. A large dev_frac flags a link inconsistent with the
    corridor FD. This is the meso 'time-dependent flow from speed' deliverable."""
    def _say(msg):
        if log is not None:
            try: log.info(msg); return
            except Exception: pass
        print(msg)
    if df.empty or "speed_qvdf_model" not in df.columns:
        return df
    df = df.copy()
    for c in ("q_qvdf_perlane", "count_total_qvdf", "theta_corridor", "lambda_link", "dev_frac"):
        df[c] = np.nan        # float cols (NaN -> blank in CSV); avoids str/float dtype clash
    dt_hr = C.DT_MIN / 60.0
    sm = pd.to_numeric(df["speed_qvdf_model"], errors="coerce")
    # Restrict to the true CONGESTION regime: speed below the cut-off (capacity) speed.
    # Above cut-off the S3 shape g(v)~0 and speed is NOT a reliable flow proxy, so the
    # FD inverse cannot recover the (high) free-flow demand -- keep observed there.
    cut = pd.to_numeric(df["cutoff"], errors="coerce")
    cong = df[sm < cut].copy()
    if cong.empty:
        _say("    conserved-flow: no congestion (speed<cutoff) intervals"); return df
    speeds, demands, vfs, idxs, lanes_l = [], [], [], [], []
    for (lid, per), gg in cong.groupby(["link_id", "period"]):
        gg = gg.sort_values("t_min")
        v = pd.to_numeric(gg["speed_qvdf_model"], errors="coerce").to_numpy(float)
        lanes = float(gg["lanes"].iloc[0]) if "lanes" in gg.columns else 1.0
        ctot = pd.to_numeric(gg["count_total_15min"], errors="coerce").fillna(0).to_numpy()
        Dpl = float(ctot.sum()) / max(lanes, 1.0)        # OBSERVED per-lane demand over episode
        if Dpl <= 0:
            # speed-only (INRIX/NVTA): no measured count -> meso target D = mu*P with
            # mu = capacity (the queue discharges at capacity over the congestion duration P).
            cap_pl = float(pd.to_numeric(gg["capacity_vphpl"], errors="coerce").iloc[0])
            P_hr = len(v) * dt_hr
            Dpl = cap_pl * P_hr
        if Dpl <= 0 or len(v) < 2:
            continue
        speeds.append(v); demands.append(Dpl); vfs.append(float(gg["free_flow"].iloc[0]))
        idxs.append(gg.index); lanes_l.append(lanes)
    if not speeds:
        _say("    conserved-flow: no usable episodes"); return df
    mvals = [fdp[l]["m"] for l in cong.link_id.unique() if l in fdp and "m" in fdp[l]]
    m_corr = float(np.median(mvals)) if mvals else 6.0
    res, theta_bar = Q.flow_from_speed_corridor(speeds, demands, vf=vfs, dt_hr=dt_hr, m=m_corr, form=form)
    for r, idx, lanes in zip(res, idxs, lanes_l):
        df.loc[idx, "q_qvdf_perlane"] = np.round(r["q"], 1)
        df.loc[idx, "count_total_qvdf"] = np.round(r["q"] * dt_hr * lanes, 1)
        df.loc[idx, "theta_corridor"] = round(r["theta"], 3)
        df.loc[idx, "lambda_link"] = round(r["lam"], 2)
        df.loc[idx, "dev_frac"] = round(r["dev_frac"], 3)
    _say(f"    conserved-flow: theta_corridor(k_c)={theta_bar:.2f}, m={m_corr:.2f}, "
         f"{len(speeds)} link-episodes, median dev={100*np.median([r['dev_frac'] for r in res]):.1f}%")
    return df


def build_handoff(cfg, a, awk, epw, epw_params, fdp, mode, out):
    ww = C.WIDE_WINDOW
    # sequential node ids per corridor (ordered by mean position == time-invariant link order)
    order = sorted([l for l in awk.link_id.unique() if l in fdp])
    node = {lid: i + 1 for i, lid in enumerate(order)}
    # PER-PERIOD full-day model reconstruction (replaces the single wide-window episode, which merges
    # AM+MD+PM into one trough on corridors that never recover above the cut-off). Gather each link's
    # observed profile, calibrate f_p/s WITHIN each period across links -- with the corridor's
    # facility-type x area-type default when a period is too thin -- then stitch a trough per period.
    windows = Q.period_windows(ww[0], ww[1])
    fa_default = C.facility_area_default(cfg.get("facility_type"), cfg.get("area_type"))
    profiles = []; ff_by_link = {}
    for lid in order:
        g = awk[(awk.link_id == lid) & (awk.t_min >= ww[0]) & (awk.t_min < ww[1])].sort_values("t_min")
        if len(g) < 8:
            continue
        raw = g.speed.to_numpy()
        profiles.append((g.t_min.to_numpy(), Q.smooth_speed(raw), C.CUTOFF_RATIO * fdp[lid]["vf"]))
        ff_by_link[lid] = float(np.nanpercentile(raw, 99))          # observed free-flow (99th pct)
    pp = Q.calibrate_perperiod(profiles, windows, default=fa_default)

    rows = []; acc = {}                                    # acc = corridor delay accounting per period
    for lid in order:
        g = awk[(awk.link_id == lid) & (awk.t_min >= ww[0]) & (awk.t_min < ww[1])].sort_values("t_min")
        if len(g) < 8:
            continue
        tm = g.t_min.to_numpy(); raw = g.speed.to_numpy(); sm = Q.smooth_speed(raw)
        flow = g.flow_pl.to_numpy() if "flow_pl" in g.columns else np.full(len(g), np.nan)
        fd = fdp[lid]; vf = fd["vf"]; cut = C.CUTOFF_RATIO * vf; cap = fd["cap"]; uc = fd["uc"]
        L = float(g.length.iloc[0]); lanes = int(g.lanes.iloc[0]) if "lanes" in g.columns else 1
        # full-day model speed: per-period QVDF troughs stitched (observed free-flow shoulders)
        model = Q.stitch_fullday_model(tm, sm, cut, ff_by_link.get(lid, vf), pp, windows)
        for k, t in enumerate(tm):
            per = Q._assign_period(t / 60.0) or "NT"
            vpl = float(flow[k]) if flow[k] == flow[k] else np.nan
            c15 = vpl * (C.DT_MIN / 60.0) if vpl == vpl else np.nan         # per-lane 15-min count
            ctot = c15 * lanes if c15 == c15 else np.nan
            vmt = (ctot * L) if ctot == ctot else np.nan
            # corridor accounting (slides 57-58): VHT, VDT = TT-FFTT, VCDT = max(0, TT-TT@capacity)
            so = max(float(raw[k]), 1.0)
            vht = ctot * (L / so) if ctot == ctot else np.nan              # veh-hours this 15-min
            vfftt = ctot * (L / vf) if ctot == ctot else np.nan            # at free-flow
            vcaptt = ctot * (L / uc) if ctot == ctot else np.nan          # at capacity speed u_c
            vdt = max(0.0, vht - vfftt) if vht == vht else np.nan      # delay >= 0 (HOV can run > posted vf)
            vcdt = max(0.0, vht - vcaptt) if vht == vht else np.nan
            if ctot == ctot:
                acc.setdefault(per, dict(VMT=0.0, VHT=0.0, VFFTT=0.0, VDT=0.0, VCDT=0.0, veh=0.0))
                a = acc[per]; a["VMT"] += vmt; a["VHT"] += vht; a["VFFTT"] += vfftt
                a["VDT"] += vdt; a["VCDT"] += vcdt; a["veh"] += ctot
            rows.append(dict(
                link_id=lid, from_node_id=node[lid], to_node_id=node[lid] + 1, t_min=int(t), period=per,
                speed_raw=round(raw[k], 2), speed_smoothed=round(sm[k], 2), speed_qvdf_model=round(model[k], 2),
                count_per_lane_15min=round(c15, 1) if c15 == c15 else "", lanes=lanes,
                count_total_15min=round(ctot, 1) if ctot == ctot else "",
                length_mi=round(L, 3), free_flow=vf, cutoff=round(cut, 1), capacity_vphpl=round(cap, 0),
                vmt=round(vmt, 2) if vmt == vmt else "", vht=round(vht, 3) if vht == vht else "",
                vdt=round(vdt, 3) if vdt == vdt else "", vcdt=round(vcdt, 3) if vcdt == vcdt else "",
                emis_co2_g_obs=round(float(co2_g_per_mile(raw[k]) * vmt), 1) if vmt == vmt else "",
                emis_co2_g_model=round(float(co2_g_per_mile(model[k]) * vmt), 1) if vmt == vmt else ""))
    df = pd.DataFrame(rows)
    # meso: corridor-regularized, demand-conserving time-dependent flow from speed
    df = add_conserved_flow(df, fdp)
    df.to_csv(os.path.join(out, "handoff_avgweekday_timedependent.csv"), index=False)
    # corridor delay accounting per period (slides 57-58)
    arows = []
    for per, a in acc.items():
        avs = a["VMT"] / a["VHT"] if a["VHT"] > 0 else 0.0                # VMT/VHT = avg speed
        arows.append([per, round(a["VMT"], 1), round(a["VHT"], 2), round(a["VFFTT"], 2),
                      round(a["VDT"], 2), round(a["VCDT"], 2), round(avs, 1),
                      round(a["VDT"] / a["VHT"] * 100, 1) if a["VHT"] > 0 else 0.0])
    pd.DataFrame(arows, columns=["period", "VMT_mi", "VHT_hr", "VFFTT_hr", "VDT_hr", "VCDT_hr",
                                 "avg_speed_mph", "delay_share_pct"]).to_csv(
        os.path.join(out, "corridor_accounting.csv"), index=False)

    # per-link QVDF parameters (for Stage II VDF + Stage III emission cost)
    prows = []
    for lid in order:
        p = None
        for per in C.PERIODS:
            p = epw_params.get(per, {}).get(lid) or p
        eps = epw[(epw.link_id == lid) & (epw.P > 0)] if len(epw) else pd.DataFrame()
        per_dom = eps.sort_values("P", ascending=False).period.iloc[0] if len(eps) else ""
        p = epw_params.get(per_dom, {}).get(lid)
        fd = fdp[lid]
        prows.append(dict(link_id=lid, from_node_id=node[lid], to_node_id=node[lid] + 1,
                          dominant_period=per_dom,
                          f_d=round(p["f_d"], 4) if p else "", n=round(p["n"], 4) if p else "",
                          f_p=round(p["f_p"], 4) if p else "", s=round(p["s"], 4) if p else "",
                          alpha=round(p["alpha"], 4) if p else "", beta=round(p["beta"], 4) if p else "",
                          free_flow=fd["vf"], speed_at_capacity_uc=round(fd["uc"], 1),
                          cutoff=round(C.CUTOFF_RATIO * fd["vf"], 1), capacity_vphpl=round(fd["cap"], 0)))
    pd.DataFrame(prows).to_csv(os.path.join(out, "handoff_link_qvdf_params.csv"), index=False)
    return df
