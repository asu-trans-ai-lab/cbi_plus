# -*- coding:utf-8 -*-
"""Stage II — time-dependent ODME driver (reads the Stage-I hand-off, runs Path4GMNS ODME per
15-min slice using the QVDF alpha/beta as the link VDF), with explicit RAMP on/off links and
net-flow conservation constraints so the corridor OD is well-determined.

Network (GMNS, written once to outputs/<KEY>/stage2_odme/network/):
    mainline nodes 1..N+1 (non-zone) chained by the N mainline links (QVDF alpha/beta VDF);
    at every mainline node i an ON-ramp origin zone (1000+i -> i) and an OFF-ramp destination
    zone (i -> 2000+i). A trip enters at an on-ramp zone, runs the mainline, exits at an off-ramp.

Net-flow / ramp constraints per 15-min slice (conservation at each mainline node):
    on[i] - off[i] = count[i] - count[i-1]     (entry: on[1]=count[1]; exit: off[N+1]=count[N])
These ramp counts + the mainline counts are all fed to ODME as measurements -> the OD is pinned.

Usage:  python stage2_odme.py I405 PM       (corridor key + period AM|MD|PM)

Outputs (outputs/<KEY>/stage2_odme/):
    network/node.csv, network/link.csv          GMNS network (mainline + ramps)
    stage2_odme_<PERIOD>_linkflow_timedependent.csv   slice x link: role, observed, odme, GEH
    stage2_odme_<PERIOD>_od_timedependent.csv         slice x (o_zone,d_zone): volume
    stage2_odme_<PERIOD>_columns_timedependent.csv    slice x route columns (path volumes)
    stage2_odme_<PERIOD>_summary.csv                  per slice: total OD, MAPE, %GEH<5 (mainline)
    fig_stage2_odme_<PERIOD>.png
"""
import os
import sys
import io
import contextlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import config as C

ON, OFF = 10000, 20000          # link-id offsets for on/off ramp connectors
ONND, OFFND = 1000, 2000        # node-id offsets for on/off ramp zones


def _geh(model, obs):
    model = np.asarray(model, float); obs = np.asarray(obs, float)
    return np.sqrt(2 * (model - obs) ** 2 / np.maximum(model + obs, 1e-6))


def _vol_col(df):
    for c in ["volume", "vol", "link_volume", "assigned_volume", "flow"]:
        if c in df.columns:
            return c
    raise KeyError(f"no volume column in {df.columns.tolist()}")


def build_network(net, links, ab):
    """write node.csv + link.csv (mainline chain + on/off ramps). Returns (N, role map link_id->role)."""
    os.makedirs(net, exist_ok=True)
    N = len(links)
    lm = links.link_id.tolist()
    cum = np.concatenate([[0.0], np.cumsum(links.length_mi.to_numpy())]) * 0.02
    nodes, role, zid = [], {}, 1
    for i in range(1, N + 2):                              # mainline nodes (non-zone)
        nodes.append((i, 0, cum[i - 1], 38.80))
    for i in range(1, N + 2):                              # ramp zones at every mainline node
        nodes.append((ONND + i, zid, cum[i - 1], 38.85)); zid += 1
        nodes.append((OFFND + i, zid, cum[i - 1], 38.75)); zid += 1
    pd.DataFrame(nodes, columns=["node_id", "zone_id", "x_coord", "y_coord"]).to_csv(
        os.path.join(net, "node.csv"), index=False)

    lr = []
    for i in range(1, N + 1):                              # mainline links (QVDF VDF)
        a, b = ab.get(lm[i - 1], (0.15, 4.0))
        r = links.iloc[i - 1]
        lr.append((i, i, i + 1, max(r.length_mi, 0.02), int(r.lanes), r.free_flow, r.capacity_vphpl,
                   1, "auto", round(a, 4), round(b, 4),
                   f"LINESTRING ({cum[i-1]:.5f} 38.8, {cum[i]:.5f} 38.8)")); role[i] = "mainline"
    for i in range(1, N + 2):                              # ramp connectors (free-flowing)
        lr.append((ON + i, ONND + i, i, 0.05, 2, 50.0, 8000.0, 2, "auto", 0.05, 4,
                   f"LINESTRING ({cum[i-1]:.5f} 38.85, {cum[i-1]:.5f} 38.8)")); role[ON + i] = "onramp"
        lr.append((OFF + i, i, OFFND + i, 0.05, 2, 50.0, 8000.0, 2, "auto", 0.05, 4,
                   f"LINESTRING ({cum[i-1]:.5f} 38.8, {cum[i-1]:.5f} 38.75)")); role[OFF + i] = "offramp"
    pd.DataFrame(lr, columns=["link_id", "from_node_id", "to_node_id", "length", "lanes",
                              "free_speed", "capacity", "link_type", "allowed_uses",
                              "vdf_alpha", "vdf_beta", "geometry"]).to_csv(
        os.path.join(net, "link.csv"), index=False)
    with open(os.path.join(net, "settings.yml"), "w") as f:
        f.write("agents:\n  - type: a\n    name: auto\n    vot: 10\n    flow_type: 0\n    pce: 1\n"
                "    free_speed: 70\n    use_link_ffs: true\ndemand_periods:\n  - period: p\n"
                "    time_period: \"0700_0800\"\ndemand_files:\n  - file_name: demand.csv\n"
                "    period: p\n    agent_type: a\n")
    return N, role


def ramp_counts(c):
    """conservation: on[i]-off[i]=c[i]-c[i-1]; entry on[1]=c[1], exit off[N+1]=c[N]."""
    N = len(c); on = np.zeros(N + 1); off = np.zeros(N + 1)
    on[0] = c[0]                                            # node 1 (entry)
    for i in range(1, N):                                   # internal nodes 2..N
        net = c[i] - c[i - 1]
        on[i] = max(net, 0.0); off[i] = max(-net, 0.0)
    off[N] = c[N - 1]                                       # node N+1 (exit)
    return on, off                                          # indexed 0..N (node i+1)


def _slice(net, N, c):
    """write demand seed + measurements (mainline + ramps) for one slice, run assignment->ODME."""
    import path4gmns as pg
    on, off = ramp_counts(c)                               # origins O=on, destinations D=off (0..N)
    # GRAVITY seed consistent with the conservation marginals: distribute each origin's inflow
    # O[i] across downstream destinations j>=i proportional to D[j]. Already ~matches the counts,
    # so ODME only fine-tunes (vs. inflating from a flat seed).
    O, D = on, off
    dem = []
    for i in range(N + 1):
        s = D[i:].sum()
        if O[i] <= 0 or s <= 0:
            continue
        for j in range(i, N + 1):
            if D[j] <= 0:
                continue
            v = O[i] * D[j] / s
            if v > 0.5:
                dem.append((2 * i + 1, 2 * j + 2, round(v, 2)))   # on-zone(node i+1) -> off-zone(node j+1)
    if not dem:
        dem = [(1, 2 * (N + 1), float(max(c.max(), 1.0)))]
    pd.DataFrame(dem, columns=["o_zone_id", "d_zone_id", "volume"]).to_csv(
        os.path.join(net, "demand.csv"), index=False)
    mrows = []
    for i in range(1, N + 1):                               # mainline counts
        mrows.append((len(mrows) + 1, "link", i, i + 1, float(c[i - 1]), "false"))
    for i in range(1, N + 2):                               # ramp counts (conservation)
        mrows.append((len(mrows) + 1, "link", ONND + i, i, float(on[i - 1]), "false"))
        mrows.append((len(mrows) + 1, "link", i, OFFND + i, float(off[i - 1]), "false"))
    pd.DataFrame(mrows, columns=["measurement_id", "measurement_type", "from_node_id",
                                 "to_node_id", "count", "upper_bound_flag"]).to_csv(
        os.path.join(net, "measurement.csv"), index=False)
    with contextlib.redirect_stdout(io.StringIO()):
        ui = pg.read_network(input_dir=net)
        pg.read_demand(ui, use_synthetic_data=False, save_synthetic_data=False, input_dir=net)
        pg.find_ue(ui, 20, 20)
        pg.read_measurements(ui, input_dir=net)
        pg.conduct_odme(ui, 50)
        pg.output_link_performance(ui, output_dir=net)
        pg.output_columns(ui, output_dir=net)
    perf = pd.read_csv(os.path.join(net, "link_performance.csv"))
    vc = _vol_col(perf)
    vol = dict(zip(perf.link_id, perf[vc]))
    cols = pd.read_csv(os.path.join(net, "route_assignment.csv")) if \
        os.path.exists(os.path.join(net, "route_assignment.csv")) else pd.DataFrame()
    return vol, cols


def _fit_curves(key, period, hp_per, links, flow_df, fac, sdir):
    """per representative link: time-dependent VOLUME fit (observed vs ODME) + SPEED fit
    (observed avg-weekday vs QVDF model). Rows = the most-congested links, cols = volume | speed."""
    main = flow_df[flow_df.role == "mainline"].copy()
    main["handoff_link_id"] = main.handoff_link_id.astype(int)
    cong = hp_per.groupby("link_id").speed_qvdf_model.min().sort_values()
    reps = [l for l in links.link_id if l in cong.index[:6].tolist()]
    if not reps:
        return
    n = len(reps)
    f, ax = plt.subplots(n, 2, figsize=(11, 2.1 * n), squeeze=False)
    for r, lid in enumerate(reps):
        hv = hp_per[hp_per.link_id == lid].sort_values("t_min")
        fv = main[main.handoff_link_id == lid].sort_values("t_min")
        th = hv.t_min / 60.0
        ax[r, 0].plot(fv.t_min / 60.0, fv.observed, "k-o", ms=2.5, label="observed")
        ax[r, 0].plot(fv.t_min / 60.0, fv.assigned_odme, "r--^", ms=2.5, label="ODME assigned")
        ax[r, 0].set_ylabel(f"link {lid}\nveh/h", fontsize=8); ax[r, 0].grid(alpha=0.3)
        ax[r, 0].tick_params(labelsize=7)
        ax[r, 1].plot(th, hv.speed_raw, "b-o", ms=2.5, label="observed (avg wk)")
        ax[r, 1].plot(th, hv.speed_qvdf_model, "k--^", ms=2.5, label="QVDF model")
        ax[r, 1].set_ylim(0, 80); ax[r, 1].grid(alpha=0.3); ax[r, 1].tick_params(labelsize=7)
        if r == 0:
            ax[r, 0].set_title("Time-dependent VOLUME fit (veh/h)", fontsize=9); ax[r, 0].legend(fontsize=7)
            ax[r, 1].set_title("Time-dependent SPEED fit (mph)", fontsize=9); ax[r, 1].legend(fontsize=7)
    ax[-1, 0].set_xlabel("hour"); ax[-1, 1].set_xlabel("hour")
    f.suptitle(f"{C.CORRIDORS[key]['name']} {period} — time-dependent volume & speed fit per link",
               fontsize=11)
    f.tight_layout(rect=[0, 0, 1, 0.98])
    f.savefig(os.path.join(sdir, f"fig_stage2_fit_{period}.png"), dpi=130); plt.close(f)


def run(key, period):
    out = os.path.join(C.OUT_ROOT, key)
    hp = os.path.join(out, "handoff_avgweekday_timedependent.csv")
    pp = os.path.join(out, "handoff_link_qvdf_params.csv")
    if not os.path.exists(hp):
        print(f"[{key}] no hand-off — run Stage I first (python run.py {key})"); return
    h = pd.read_csv(hp); par = pd.read_csv(pp)
    win = C.PERIODS[period]; hp_per = h[(h.t_min >= win[0]) & (h.t_min < win[1])].copy()
    if hp_per.empty:
        print(f"[{key}] no hand-off rows in {period}"); return
    links = (hp_per.sort_values("from_node_id").groupby("link_id", sort=False)
             .agg(from_node_id=("from_node_id", "first"), length_mi=("length_mi", "first"),
                  lanes=("lanes", "first"), free_flow=("free_flow", "first"),
                  capacity_vphpl=("capacity_vphpl", "first")).reset_index()
             .sort_values("from_node_id").reset_index(drop=True))
    ab = {r.link_id: (float(r.alpha) if pd.notna(r.alpha) else 0.15,
                      float(r.beta) if pd.notna(r.beta) else 4.0) for r in par.itertuples()}
    sdir = os.path.join(out, "stage2_odme"); net = os.path.join(sdir, "network")
    N, role = build_network(net, links, ab)
    fac = 60.0 / C.DT_MIN
    slices = sorted(hp_per.t_min.unique())
    print(f"[{key}] Stage-II ODME (ramps), {period}: {N} mainline links + {2*(N+1)} ramps "
          f"x {len(slices)} slices")
    flow_rows, od_rows, col_rows, summ = [], [], [], []
    all_vol_sq, all_spd_sq = [], []                        # pooled errors for the OVERALL RMSE
    for t in slices:
        sl = hp_per[hp_per.t_min == t].set_index("link_id").reindex(links.link_id)
        c = sl.count_total_15min.fillna(0).to_numpy() * fac
        if c.sum() <= 0:
            continue
        try:
            vol, cols = _slice(net, N, c)
        except Exception as e:
            print(f"    slice {t}: ODME failed ({e})"); continue
        on, off = ramp_counts(c)
        mobs, modeled = [], []
        for i in range(1, N + 1):                          # mainline obs vs odme
            o = c[i - 1]; m = vol.get(i, 0.0); hlid = int(links.link_id.iloc[i - 1])
            mobs.append(o); modeled.append(m)
            flow_rows.append([t, i, hlid, "mainline", round(o, 1), round(m, 1), round(_geh(m, o), 2)])
        for i in range(1, N + 2):                           # ramp obs vs odme
            flow_rows.append([t, ON + i, "", "onramp", round(on[i - 1], 1), round(vol.get(ON + i, 0.0), 1),
                              round(_geh(vol.get(ON + i, 0.0), on[i - 1]), 2)])
            flow_rows.append([t, OFF + i, "", "offramp", round(off[i - 1], 1), round(vol.get(OFF + i, 0.0), 1),
                              round(_geh(vol.get(OFF + i, 0.0), off[i - 1]), 2)])
        modeled_a, mobs_a = np.array(modeled), np.array(mobs)
        geh = _geh(modeled_a, mobs_a)
        vol_rmse = float(np.sqrt(np.mean((modeled_a - mobs_a) ** 2)))
        mape = np.mean(np.abs(modeled_a - mobs_a) / np.maximum(mobs_a, 1)) * 100
        all_vol_sq.extend(((modeled_a - mobs_a) ** 2).tolist())
        # time-dependent SPEED fit this slice (observed avg-weekday vs QVDF model, mainline links)
        so = sl.speed_raw.to_numpy(float); smod = sl.speed_qvdf_model.to_numpy(float)
        msk = np.isfinite(so) & np.isfinite(smod) & (so > 0)
        spd_mape = float(np.mean(np.abs(so[msk] - smod[msk]) / so[msk]) * 100) if msk.any() else np.nan
        spd_rmse = float(np.sqrt(np.mean((so[msk] - smod[msk]) ** 2))) if msk.any() else np.nan
        all_spd_sq.extend(((so[msk] - smod[msk]) ** 2).tolist())
        if len(cols):
            ovc = _vol_col(cols) if any(x in cols.columns for x in
                                        ["volume", "vol", "link_volume", "assigned_volume", "flow"]) else None
            for _, rr in cols.iterrows():
                od_rows.append([t, rr.get("o_zone_id", rr.get("from_zone_id")),
                                rr.get("d_zone_id", rr.get("to_zone_id")),
                                rr.get(ovc, rr.get("volume", 0)) if ovc else rr.get("volume", 0)])
            cc = cols.copy(); cc.insert(0, "t_min", t); col_rows.append(cc)
        summ.append([t, round(c.sum(), 0), round(vol_rmse, 1), round(spd_rmse, 2),
                     round(mape, 1), round(spd_mape, 1), round((geh < 5).mean() * 100, 1)])
    if not summ:
        print(f"[{key}] no congested slices in {period}"); return
    flow_df = pd.DataFrame(flow_rows, columns=["t_min", "link_id", "handoff_link_id", "role",
                                               "observed", "assigned_odme", "GEH"])
    flow_df.to_csv(os.path.join(sdir, f"stage2_odme_{period}_linkflow_timedependent.csv"), index=False)
    od = pd.DataFrame(od_rows, columns=["t_min", "o_zone_id", "d_zone_id", "volume"])
    od.to_csv(os.path.join(sdir, f"stage2_odme_{period}_od_timedependent.csv"), index=False)
    if col_rows:
        pd.concat(col_rows, ignore_index=True).to_csv(
            os.path.join(sdir, f"stage2_odme_{period}_columns_timedependent.csv"), index=False)
    sm = pd.DataFrame(summ, columns=["t_min", "total_OD_hourly_equiv", "vol_RMSE_vph",
                                     "speed_RMSE_mph", "vol_MAPE_pct", "speed_MAPE_pct", "pct_GEH_lt5"])
    sm.to_csv(os.path.join(sdir, f"stage2_odme_{period}_summary.csv"), index=False)
    # OVERALL (pooled across all slices x links) RMSE — the headline time-dependent measure
    ov_vol = float(np.sqrt(np.mean(all_vol_sq))) if all_vol_sq else float("nan")
    ov_spd = float(np.sqrt(np.mean(all_spd_sq))) if all_spd_sq else float("nan")

    f, ax = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    th = sm.t_min / 60.0
    ax[0].plot(th, sm.total_OD_hourly_equiv, "b-o", ms=3); ax[0].grid(alpha=0.3)
    ax[0].set_ylabel("Estimated total OD\n(veh/h equiv)")
    ax[0].set_title(f"{C.CORRIDORS[key]['name']} {period} — Stage-II time-dependent ODME (with ramps)")
    # PRIMARY measure: time-dependent RMSE — volume (veh/h, left) and speed (mph, right)
    ax[1].plot(th, sm.vol_RMSE_vph, "r-o", ms=3, label="VOLUME RMSE (veh/h)")
    ax[1].set_ylabel("volume RMSE (veh/h)", color="r"); ax[1].tick_params(axis="y", labelcolor="r")
    ax[1].grid(alpha=0.3)
    a1b = ax[1].twinx(); a1b.plot(th, sm.speed_RMSE_mph, "m-s", ms=3, label="SPEED RMSE (mph)")
    a1b.set_ylabel("speed RMSE (mph)", color="m"); a1b.tick_params(axis="y", labelcolor="m")
    ax[1].set_title(f"Time-dependent RMSE  —  OVERALL: volume {ov_vol:.0f} veh/h, speed {ov_spd:.1f} mph",
                    fontsize=10)
    l1, la1 = ax[1].get_legend_handles_labels(); l2, la2 = a1b.get_legend_handles_labels()
    ax[1].legend(l1 + l2, la1 + la2, fontsize=8, loc="upper right")
    # secondary: MAPE + gate
    ax[2].plot(th, sm.vol_MAPE_pct, "r--o", ms=2.5, label="volume MAPE %")
    ax[2].plot(th, sm.speed_MAPE_pct, "m--s", ms=2.5, label="speed MAPE %")
    ax[2].plot(th, sm.pct_GEH_lt5, "g-^", ms=3, label="% mainline GEH<5")
    ax[2].axhline(85, color="green", ls=":", lw=1)
    ax[2].set_xlabel("hour"); ax[2].set_ylabel("MAPE % / GEH"); ax[2].legend(fontsize=8); ax[2].grid(alpha=0.3)
    f.tight_layout(); f.savefig(os.path.join(sdir, f"fig_stage2_odme_{period}.png"), dpi=130); plt.close(f)
    _fit_curves(key, period, hp_per, links, flow_df, fac, sdir)
    print(f"[{key}] {period}: OVERALL RMSE  volume {ov_vol:.0f} veh/h, speed {ov_spd:.1f} mph  | "
          f"%GEH<5 {sm.pct_GEH_lt5.median():.0f}% (vol MAPE {sm.vol_MAPE_pct.median():.1f}%, "
          f"speed MAPE {sm.speed_MAPE_pct.median():.1f}%)")
    print(f"  GMNS net: network/node.csv, network/link.csv  | time-dependent: "
          f"linkflow / od / columns _{period}_*.csv")


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "I405"
    period = sys.argv[2] if len(sys.argv) > 2 else "PM"
    run(key, period)
