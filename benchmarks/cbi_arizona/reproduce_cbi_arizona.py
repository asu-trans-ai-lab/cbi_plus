# -*- coding: utf-8 -*-
"""CBI-main repo — reproduction on ITS OWN Arizona sample.

The original CBI tool shipped a 432-TMC Arizona INRIX sample (Jan 2019,
Reading.csv) together with its own computed outputs (link_cbi_summary.csv:
per-link AM/MD/PM congestion duration P, v_t2, D/C...). This script runs the
MODERN cbi_plus pipeline (io_unified INRIX loader -> stage-1 QC -> stage-2
episode scan) on that same feed and compares per-(link, period) congestion
duration and lowest speed against the legacy tool's own summary.

Agreement is the reproduction target — the two scanners differ in QC and in
sustained-crossing rules (the modern scan is hardened), so we report
correlation + median absolute difference, not exactness.

Run:  python reproduce_cbi_arizona.py     (~3-6 min: 3.8M readings)
Outputs: figures/cbi_agreement.png, figures/corridor_heatmap.png,
         legacy_vs_modern_comparison.csv, agreement_stats.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))          # repo root -> cbi_pipeline
from cbi_pipeline import io_unified, stage1_qc, stage2_episodes  # noqa: E402

FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)


def main():
    print("loading Arizona INRIX sample (432 TMCs, Jan 2019)...")
    df = io_unified.load_inrix(HERE / "data" / "Reading.csv.gz",
                               HERE / "data" / "TMC_Identification.csv",
                               s3_prior="cbi_default")
    print(f"  {len(df):,} rows / {df['sensor_uid'].nunique()} TMCs")

    df_qc, _ = stage1_qc.run_qc(df, v_c_mph=50.0, v_f_mph=70.0)
    eps, _, _ = stage2_episodes.run_episodes(df_qc, default_v_c_mph=50.0)
    val = eps[eps["dc_existence"]].copy()
    val["tmc"] = val["sensor_uid"].str.replace("inrix::", "", regex=False)

    # modern per-(tmc, period): mean P over days, min-speed median
    ours = (val.groupby(["tmc", "period"])
               .agg(P_modern_h=("P_min", lambda s: s.mean() / 60.0),
                    vt2_modern=("min_speed_mph", "median"))
               .reset_index())

    ref = pd.read_csv(HERE / "reference" / "link_cbi_summary.csv.gz")
    rows = []
    for per in ("AM", "MD", "PM"):
        sub = ref[["tmc", f"{per}_P", f"{per}_vt2"]].dropna()
        sub = sub.rename(columns={f"{per}_P": "P_legacy_h", f"{per}_vt2": "vt2_legacy"})
        sub["period"] = per
        rows.append(sub)
    legacy = pd.concat(rows, ignore_index=True)

    cmp_ = ours.merge(legacy, on=["tmc", "period"], how="inner")
    cmp_ = cmp_[(cmp_["P_legacy_h"] >= 0) & np.isfinite(cmp_["P_modern_h"])]
    cmp_.round(3).to_csv(HERE / "legacy_vs_modern_comparison.csv", index=False)

    stats = []
    for per, g in cmp_.groupby("period"):
        both = g[(g["P_legacy_h"] > 0) & (g["P_modern_h"] > 0)]
        stats.append(dict(
            period=per, n_links=len(g), n_congested_both=len(both),
            P_corr=round(float(both["P_legacy_h"].corr(both["P_modern_h"])), 3) if len(both) > 5 else None,
            P_mae_h=round(float((both["P_legacy_h"] - both["P_modern_h"]).abs().median()), 3) if len(both) else None,
            vt2_corr=round(float(both["vt2_legacy"].corr(both["vt2_modern"])), 3) if len(both) > 5 else None,
            vt2_mae=round(float((both["vt2_legacy"] - both["vt2_modern"]).abs().median()), 2) if len(both) else None))
    st = pd.DataFrame(stats)
    st.to_csv(HERE / "agreement_stats.csv", index=False)
    print(st.to_string(index=False))

    # agreement figure
    fig, ax = plt.subplots(1, 2, figsize=(12.4, 5))
    cols = {"AM": "#2563eb", "MD": "#c07a12", "PM": "#b3261e"}
    for per, g in cmp_.groupby("period"):
        ax[0].scatter(g["P_legacy_h"], g["P_modern_h"], s=9, alpha=.55,
                      c=cols[per], label=per)
        ax[1].scatter(g["vt2_legacy"], g["vt2_modern"], s=9, alpha=.55,
                      c=cols[per], label=per)
    for a, lim in ((ax[0], 8), (ax[1], 70)):
        a.plot([0, lim], [0, lim], "k--", lw=1)
        a.legend()
    ax[0].set_xlabel("legacy CBI tool P (h)"); ax[0].set_ylabel("modern cbi_plus P (h)")
    ax[0].set_title("congestion duration per (link, period)")
    ax[1].set_xlabel("legacy v_t2 (mph)"); ax[1].set_ylabel("modern v_t2 (mph)")
    ax[1].set_title("lowest speed per (link, period)")
    fig.suptitle("Legacy CBI-main vs modern cbi_plus — same Arizona data")
    fig.tight_layout(); fig.savefig(FIG / "cbi_agreement.png", dpi=140); plt.close(fig)

    # corridor heatmap for the busiest corridor-day (context figure)
    one = df_qc[df_qc["qc_pass"] == 1].copy()
    one["date"] = pd.to_datetime(one["datetime"]).dt.date.astype(str)
    corr_id = one.groupby("corridor")["sensor_uid"].nunique().idxmax()
    sub = one[one["corridor"] == corr_id]
    day = sub.groupby("date")["speed_mph"].mean().idxmin()
    sub = sub[sub["date"] == day]
    piv = sub.pivot_table(index="road_order", columns=pd.to_datetime(sub["datetime"]).dt.hour * 12
                          + pd.to_datetime(sub["datetime"]).dt.minute // 5,
                          values="speed_mph")
    fig, ax = plt.subplots(figsize=(11, 4.6))
    im = ax.imshow(piv.to_numpy(), aspect="auto", cmap="RdYlGn", vmin=10, vmax=70,
                   extent=[0, 24, float(piv.index.max()), float(piv.index.min())])
    fig.colorbar(im, label="speed (mph)")
    ax.set_xlabel("hour of day"); ax.set_ylabel("road order (upstream → downstream)")
    ax.set_title(f"corridor {corr_id} — worst day {day} (modern QC'd field)")
    fig.tight_layout(); fig.savefig(FIG / "corridor_heatmap.png", dpi=140); plt.close(fig)
    print("wrote figures/ + legacy_vs_modern_comparison.csv + agreement_stats.csv")


if __name__ == "__main__":
    main()
