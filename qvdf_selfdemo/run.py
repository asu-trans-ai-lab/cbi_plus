# -*- coding:utf-8 -*-
"""
QVDF turn-key pipeline runner.

Usage:
    python run.py                 # run every corridor in config.CORRIDORS
    python run.py I405            # one corridor (California PeMS)
    python run.py I405 NVTA_NB    # several
"""
import sys
import config as C
from pipeline import run_corridor

def _cross_corridor_summary(keys):
    """Aggregate the per-corridor quality into one comparison table (I-10 -> I-405 -> NVTA ...)."""
    import os, pandas as pd
    rows = []
    for k in keys:
        out = os.path.join(C.OUT_ROOT, k)
        cf = os.path.join(out, "Quality_calibration.csv"); tf = os.path.join(out, "Quality_timeseries.csv")
        gf = os.path.join(out, "quality_gates.csv")
        if not (os.path.exists(cf) and os.path.getsize(cf) > 5):
            continue
        try:
            cal = pd.read_csv(cf); ts = pd.read_csv(tf); g = pd.read_csv(gf)
        except Exception:
            continue
        if len(cal) == 0:
            continue
        for _, r in cal.iterrows():
            gp = g[g.period == r.period]
            rows.append(dict(corridor=C.CORRIDORS[k]["name"], key=k, period=r.period,
                             mode=C.CORRIDORS[k].get("wd_mode"), n_links=r.n_links,
                             step1_DC_P_R2=r.step1_DC_P_R2, step2_P_mag_R2=r.step2_P_mag_R2,
                             P_MAPE_pct=r.P_MAPE_pct, vt2_MAPE_pct=r.vt2_MAPE_pct,
                             t0_MAE_min=r.t0_MAE_min,
                             smooth_R2_med=round(ts.smooth_vs_raw_R2.median(), 3),
                             gates_pass=f"{(gp.status=='PASS').sum()}/{len(gp)}"))
    if rows:
        df = pd.DataFrame(rows)
        path = os.path.join(C.OUT_ROOT, "_QUALITY_SUMMARY.csv")
        df.to_csv(path, index=False)
        print("\n================ CROSS-CORRIDOR QUALITY SUMMARY ================")
        print(df.drop(columns=["key", "mode"]).to_string(index=False))
        print(f"\nwrote {path}")


if __name__ == "__main__":
    keys = sys.argv[1:] or list(C.CORRIDORS.keys())
    ran = []
    for k in keys:
        if k not in C.CORRIDORS:
            print(f"unknown corridor '{k}'. Available: {list(C.CORRIDORS)}"); continue
        try:
            run_corridor(k); ran.append(k)
        except Exception as e:
            import traceback
            print(f"[{k}] pipeline error: {e}"); traceback.print_exc()
    if ran:
        _cross_corridor_summary(ran)
        try:
            import dashboard
            dashboard.build_dashboard(ran)
        except Exception as e:
            print(f"dashboard error: {e}")
