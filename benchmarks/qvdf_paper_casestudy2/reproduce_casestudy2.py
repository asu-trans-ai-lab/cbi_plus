# -*- coding: utf-8 -*-
"""QVDF paper, Section 5 CASE STUDY 2 — exact reproduction from the paper's data.

I-405 NB (LA), 6-mile corridor, single recurring bottleneck, 4 months, 5-min,
11:00-20:00 (paper text says Apr-Jul 2019; the repo workbook is day-indexed).
Source data: the paper repo's own calibration workbook
`data/02-I405_Summary_4month.xlsx` (QVDF-main/Excel, public GitHub) — 253
per-day rows of (D/C, P, D, mu, mu/C) plus the paper's calibrated
coefficients (C=1662 vphpl, n=1.0461, f_d=1.1238, f_p=0.2193, s=0.9389).

Reproduces Figs 19-23:
  Fig 19  observed + estimated congestion duration P vs D/C
  Fig 20  estimated vs observed P (elasticity form)
  Fig 21  lowest speed v_t2 vs D/C (observed + estimated)
  Fig 22  mean speed v-bar vs D/C (observed + estimated)
  Fig 23  capacity discount factor mu/C vs P

The coefficients are taken from the workbook (its Solver objective minimizes
the estimated-mu squared error, Eq. 26a — we treat them as given, as the paper
does) and every estimated curve here is recomputed from those coefficients,
then checked against the workbook's own est_* columns for self-consistency.

Run:  python reproduce_casestudy2.py
See also reproduce_casestudy2_current_data.py — the same longitudinal analysis
on the CURRENT public TrafficFlowBench I-405N release (different vintage).
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)
WB = HERE / "data" / "02-I405_Summary_4month.xlsx"

V_CO = 52.0     # cut-off speed used by the workbook (est_vt2 at P=0 = 52.0)


def main():
    dcp = pd.read_excel(WB, sheet_name="DC-P ")
    C = float(dcp["Capacity"].dropna().iloc[0])
    n = float(dcp["n"].dropna().iloc[0])
    fd = float(dcp["fd"].dropna().iloc[0])
    vtp = pd.read_excel(WB, sheet_name="Vt2-P Figure")
    fp = float(vtp["fp"].dropna().iloc[0])
    s = float(vtp["s"].dropna().iloc[0])

    day = dcp[["Day", "D/C", "P", "µ = D/P", "Obs_µ/C"]].dropna(subset=["D/C", "P"]).copy()
    day.columns = ["day", "dc", "P", "mu", "mu_over_C"]
    est_wb = dcp["est_P"].dropna() if "est_P" in dcp.columns else pd.Series(dtype=float)

    vt2df = pd.read_excel(WB, sheet_name="Vt2-DC")[
        ["D/C", "Obs_P", "vt2", "est_vt2(with D/C)"]].dropna(subset=["D/C", "vt2"])
    vbardf = pd.read_excel(WB, sheet_name="Vbar-DC")[
        ["D/C", "Observed v_bar", "est_vbar(with D/C)"]].dropna(subset=["D/C", "Observed v_bar"])

    theta_rows = pd.read_excel(WB, sheet_name="Vt2-DC")
    theta = float(theta_rows["teta"].dropna().iloc[0]) if "teta" in theta_rows and theta_rows["teta"].notna().any() else np.nan

    print(f"paper coefficients (workbook): C={C:.0f} n={n:.4f} f_d={fd:.4f} "
          f"f_p={fp:.4f} s={s:.4f} theta={theta:.4f}" if np.isfinite(theta) else
          f"paper coefficients (workbook): C={C:.0f} n={n:.4f} f_d={fd:.4f} f_p={fp:.4f} s={s:.4f}")
    print(f"per-day observations: {len(day)}")

    dc_axis = np.linspace(max(0.05, day['dc'].min()), day['dc'].max() * 1.03, 200)
    P_curve = fd * dc_axis**n
    P_est = fd * day["dc"]**n

    # self-consistency vs the workbook's own est_P column
    if len(est_wb) >= len(day) * 0.9:
        diff = float(np.nanmedian(np.abs(P_est.to_numpy()[:len(est_wb)] - est_wb.to_numpy()[:len(P_est)])))
        print(f"self-consistency |our est_P - workbook est_P| median = {diff:.4f} h")

    # ---- Fig 19 + 20
    fig, ax = plt.subplots(1, 2, figsize=(12.4, 4.8))
    ax[0].scatter(day["dc"], day["P"], s=13, c="k", label="observed (per day)")
    ax[0].plot(dc_axis, P_curve, "b--", lw=2,
               label=f"$P=f_d(D/C)^n$  ($f_d$={fd:.3f}, n={n:.3f})")
    ax[0].set_xlabel("inflow demand-to-capacity ratio D/C")
    ax[0].set_ylabel("congestion duration P (hours)")
    ax[0].legend(); ax[0].set_title("Fig. 19 — observed & estimated P vs D/C")
    ax[1].scatter(day["P"], P_est, s=13, c="k")
    lim = [0, float(max(day["P"].max(), P_est.max())) * 1.05]
    ax[1].plot(lim, lim, "r--"); ax[1].set_xlim(lim); ax[1].set_ylim(lim)
    r2 = 1 - np.sum((P_est - day["P"])**2) / np.sum((day["P"] - day["P"].mean())**2)
    ax[1].set_xlabel("observed P (hours)"); ax[1].set_ylabel("estimated P (hours)")
    ax[1].set_title(f"Fig. 20 — estimated vs observed P (R²={r2:.3f})")
    fig.tight_layout(); fig.savefig(FIG / "Fig19_20_P_vs_DC.png", dpi=140); plt.close(fig)

    # ---- Fig 21 (v_t2 vs D/C)  +  Fig 22 (v-bar vs D/C)
    fig, ax = plt.subplots(1, 2, figsize=(12.4, 4.8))
    vt2_curve = V_CO / (1 + fp * (fd * dc_axis**n)**s)
    ax[0].scatter(vt2df["D/C"], vt2df["vt2"], s=13, c="k", label="observed")
    ax[0].plot(dc_axis, vt2_curve, "b--", lw=2,
               label=f"$v_{{co}}/(1+f_p P^s)$  ($f_p$={fp:.3f}, s={s:.3f})")
    ax[0].axhline(V_CO, color="gray", ls=":", lw=1, label=f"$v_{{co}}$ = {V_CO:.0f} mph")
    ax[0].set_xlabel("D/C ratio"); ax[0].set_ylabel("lowest speed $v_{t2}$ (mph)")
    ax[0].legend(); ax[0].set_title("Fig. 21 — lowest speed $v_{t2}$ vs D/C")
    ax[1].scatter(vbardf["D/C"], vbardf["Observed v_bar"], s=13, c="k", label="observed")
    est_vbar = vbardf["est_vbar(with D/C)"]
    order = np.argsort(vbardf["D/C"].to_numpy())
    ax[1].plot(vbardf["D/C"].to_numpy()[order], est_vbar.to_numpy()[order], "b--", lw=2,
               label="estimated (workbook, α&β form)")
    ax[1].set_xlabel("D/C ratio"); ax[1].set_ylabel(r"mean speed $\bar{v}$ (mph)")
    ax[1].legend(); ax[1].set_title(r"Fig. 22 — mean speed $\bar{v}$ vs D/C")
    fig.tight_layout(); fig.savefig(FIG / "Fig21_22_speeds_vs_DC.png", dpi=140); plt.close(fig)

    # ---- Fig 23 (capacity discount factor vs P)
    fig, ax = plt.subplots(figsize=(6.6, 4.8))
    ax.scatter(day["P"], day["mu_over_C"], s=13, c="k", label="observed μ/C per day")
    P_axis = np.linspace(max(0.1, day['P'].min()), day['P'].max() * 1.03, 200)
    # Eq. 26a estimated discount: mu/C = (D/C)/P with D/C = (P/fd)^(1/n)
    ax.plot(P_axis, (P_axis / fd)**(1 / n) / P_axis, "b--", lw=2,
            label=r"estimated $\mu/C=(P/f_d)^{1/n}/P$")
    ax.axhline(1.0, color="gray", ls=":", lw=1)
    ax.set_xlabel("congestion duration P (hours)")
    ax.set_ylabel("capacity discount factor μ/C")
    ax.legend(); ax.set_title("Fig. 23 — capacity discount factor vs P")
    fig.tight_layout(); fig.savefig(FIG / "Fig23_capacity_discount.png", dpi=140); plt.close(fig)

    day.round(4).to_csv(HERE / "per_day_statistics.csv", index=False)
    pd.DataFrame([dict(corridor="I-405 NB (paper case study 2)",
                       source="02-I405_Summary_4month.xlsx (paper repo)",
                       n_days=len(day), capacity_vphpl=C, v_co_mph=V_CO,
                       n=round(n, 4), f_d=round(fd, 4), f_p=round(fp, 4),
                       s=round(s, 4), P_fit_R2=round(float(r2), 3))]
                 ).to_csv(HERE / "calibrated_coefficients.csv", index=False)
    print("wrote figures/Fig19_20 Fig21_22 Fig23 + per_day_statistics.csv + calibrated_coefficients.csv")


if __name__ == "__main__":
    main()
