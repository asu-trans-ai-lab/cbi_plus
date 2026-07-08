# -*- coding: utf-8 -*-
"""QVDF paper, Section 5 CASE STUDY 2 — longitudinal single-bottleneck analysis.

Paper setting (Zhou, Cheng, Wu et al. 2022, Figs 18-23): I-405 NB, Los Angeles,
Abs MP 8.97-14.77, 22 detectors, 5-min data, 11:00-20:00, April-July 2019, one
recurring bottleneck studied longitudinally: observed vs estimated congestion
duration P vs D/C (Figs 19-20), lowest speed v_t2 vs D/C (Fig 21), mean speed
v-bar vs D/C (Fig 22), and capacity discount factor vs P (Fig 23).

DATA VINTAGE NOTE (deliberate): the paper's Apr-Jul 2019 extract is not in any
of the four public repos, so this is a METHODOLOGICAL REPLICATION on the
current public TrafficFlowBench I-405 N release (Caltrans PeMS, 2025-26):
same freeway, same direction, same 4-month span (April-July), same 11:00-20:00
window, same per-day statistics and the same elasticity fits — at the
corridor's strongest recurring bottleneck (chosen by the stage-6 CBI ranking).
Numbers legitimately differ from the paper; the CURVES and elasticities are
the reproduction target. Drop the original 2019 extract into data/ with the
same schema to reproduce the paper's exact numbers.

Run:  python reproduce_casestudy2.py [--station 775155] [--year 2026]
Needs: TFB_DATA_ROOT env var or the default TrafficFlowBench path.
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

TFB = Path(os.environ.get(
    "TFB_DATA_ROOT",
    "C:/source_codes/0_source_code_new/IEEE_Simulate_Players/"
    "ASU_Internal_Version_DLSIM_IEEE/02_data_PeMS_LA")) / "release" / "I-405N"

V_CO_FRAC = 0.7            # cut-off speed = 70% of free-flow (paper: 49/70 mph)
T_START, T_END = 11, 20    # 11:00-20:00 analysis window (paper)
MONTHS = (4, 5, 6, 7)      # April-July (paper)


def load_series(station: int, year: int) -> pd.DataFrame:
    df = pd.read_parquet(TFB / "train_detector_states.parquet",
                         columns=["date", "timestamp", "station_id",
                                  "speed", "flow", "is_observed"])
    df = df[df["station_id"] == station].copy()
    if "is_observed" in df.columns:
        df = df[df["is_observed"].astype(bool)]
    ts = pd.to_datetime(df["timestamp"].str.replace("Z", ""))
    df["dt"] = ts
    df = df[(ts.dt.year == year) & (ts.dt.month.isin(MONTHS))
            & (ts.dt.hour >= T_START) & (ts.dt.hour < T_END)]
    df["speed_mph"] = df["speed"] / 1.609
    # effective lanes from p99 flow (never trust map lanes)
    lanes = max(2, min(6, round(float(np.nanpercentile(df["flow"], 99)) / 2000)))
    df["q_vphpl"] = df["flow"] / lanes
    return df.sort_values("dt")


def per_day_stats(df: pd.DataFrame) -> pd.DataFrame:
    vf = float(np.nanpercentile(df["speed_mph"], 95))
    v_co = V_CO_FRAC * vf
    cap = float(np.nanpercentile(df["q_vphpl"], 98))
    rows = []
    for date, g in df.groupby(df["dt"].dt.date):
        v = g["speed_mph"].to_numpy()
        q = g["q_vphpl"].to_numpy()
        if np.isfinite(v).sum() < 60:
            continue
        below = np.where(v < v_co)[0]
        if below.size == 0:
            rows.append(dict(date=date, P=0.0, DC=np.nan, vt2=np.nan,
                             vbar=np.nan, mu=np.nan, dow=pd.Timestamp(date).dayofweek))
            continue
        t2 = int(np.nanargmin(v))
        t0 = t2
        while t0 > 0 and (not np.isfinite(v[t0 - 1]) or v[t0 - 1] < v_co):
            t0 -= 1
        t3 = t2
        while t3 < len(v) - 1 and (not np.isfinite(v[t3 + 1]) or v[t3 + 1] < v_co):
            t3 += 1
        P = (t3 - t0 + 1) * 5 / 60.0
        D = float(np.nansum(q[t0:t3 + 1]) * 5 / 60.0)     # per-lane vehicles
        mu = float(np.nanmedian(q[t2:t3 + 1]))            # discharge (t2..t3]
        rows.append(dict(date=date, P=P, DC=D / cap, vt2=float(v[t2]),
                         vbar=float(np.nanmean(v[t0:t3 + 1])), mu=mu,
                         dow=pd.Timestamp(date).dayofweek))
    out = pd.DataFrame(rows)
    out.attrs.update(vf=vf, v_co=v_co, cap=cap)
    return out


def powfit(x, y):
    m = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    if m.sum() < 5:
        return np.nan, np.nan
    b, a = np.polyfit(np.log(x[m]), np.log(y[m]), 1)
    return float(np.exp(a)), float(b)      # y = a * x^b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--station", type=int, default=775155,
                    help="bottleneck station (default: top of stage-6 CBI ranking)")
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args()

    df = load_series(a.station, a.year)
    st = per_day_stats(df)
    cong = st[st["P"] > 0.25].copy()
    vf, v_co, cap = st.attrs["vf"], st.attrs["v_co"], st.attrs["cap"]
    f_d, n = powfit(cong["DC"].to_numpy(), cong["P"].to_numpy())
    msr = v_co / cong["vt2"] - 1
    f_p, s = powfit(cong["P"].to_numpy(), msr.to_numpy())
    print(f"station {a.station} · Apr-Jul {a.year} · vf={vf:.1f} v_co={v_co:.1f} "
          f"C={cap:.0f} vphpl · {len(cong)} congested days")
    print(f"calibrated: f_d={f_d:.3f} n={n:.3f} | f_p={f_p:.3f} s={s:.3f}")

    dc = np.linspace(max(0.2, cong['DC'].min()), cong['DC'].max() * 1.05, 100)

    # Fig 19/20 — P vs D/C, observed + estimated (elasticity form)
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    ax[0].scatter(cong["DC"], cong["P"], s=14, c="k", label="observed day")
    ax[0].plot(dc, f_d * dc**n, "b--", lw=2, label=f"$P=f_d(D/C)^n$, $f_d$={f_d:.2f}, n={n:.2f}")
    ax[0].set_xlabel("D/C ratio"); ax[0].set_ylabel("congestion duration P (h)")
    ax[0].legend(); ax[0].set_title("Fig 19-analog — observed & estimated P vs D/C")
    Pest = f_d * cong["DC"]**n
    ax[1].scatter(cong["P"], Pest, s=14, c="k")
    lim = [0, max(cong["P"].max(), Pest.max()) * 1.05]
    ax[1].plot(lim, lim, "r--"); ax[1].set_xlim(lim); ax[1].set_ylim(lim)
    r2 = 1 - np.nansum((Pest - cong["P"])**2) / np.nansum((cong["P"] - cong["P"].mean())**2)
    ax[1].set_xlabel("observed P (h)"); ax[1].set_ylabel("estimated P (h)")
    ax[1].set_title(f"Fig 20-analog — estimated vs observed P (R²={r2:.2f})")
    fig.tight_layout(); fig.savefig(FIG / "Fig19_20_P_vs_DC.png", dpi=140); plt.close(fig)

    # Fig 21 — v_t2 vs D/C ; Fig 22 — v-bar vs D/C
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    vt2_est = v_co / (1 + f_p * (f_d * dc**n)**s)
    ax[0].scatter(cong["DC"], cong["vt2"], s=14, c="k", label="observed")
    ax[0].plot(dc, vt2_est, "b--", lw=2, label=f"$v_c/(1+f_p P^s)$, $f_p$={f_p:.2f}, s={s:.2f}")
    ax[0].axhline(v_co, color="gray", ls=":", label=f"$v_{{co}}$={v_co:.0f}")
    ax[0].set_xlabel("D/C ratio"); ax[0].set_ylabel("lowest speed $v_{t2}$ (mph)")
    ax[0].legend(); ax[0].set_title("Fig 21-analog — lowest speed vs D/C")
    theta = cong["vbar"].mean() / cong["vt2"].mean()
    ax[1].scatter(cong["DC"], cong["vbar"], s=14, c="k", label="observed")
    ax[1].plot(dc, vt2_est * theta, "b--", lw=2, label=f"θ·$v_{{t2}}$ est (θ={theta:.2f})")
    ax[1].set_xlabel("D/C ratio"); ax[1].set_ylabel("mean congested speed (mph)")
    ax[1].legend(); ax[1].set_title("Fig 22-analog — mean speed vs D/C")
    fig.tight_layout(); fig.savefig(FIG / "Fig21_22_speeds_vs_DC.png", dpi=140); plt.close(fig)

    # Fig 23 — capacity discount factor (mu/C) vs P
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    ax.scatter(cong["P"], cong["mu"] / cap, s=14, c="k")
    ax.axhline(1.0, color="gray", ls=":")
    ax.set_xlabel("congestion duration P (h)")
    ax.set_ylabel("capacity discount factor μ/C")
    ax.set_title("Fig 23-analog — capacity discount vs P")
    fig.tight_layout(); fig.savefig(FIG / "Fig23_capacity_discount.png", dpi=140); plt.close(fig)

    cong.round(3).to_csv(HERE / "per_day_statistics.csv", index=False)
    pd.DataFrame([dict(station=a.station, year=a.year, months="Apr-Jul",
                       window="11:00-20:00", vf_mph=round(vf, 1),
                       v_co_mph=round(v_co, 1), capacity_vphpl=round(cap),
                       n_congested_days=len(cong), f_d=round(f_d, 3),
                       n=round(n, 3), f_p=round(f_p, 3), s=round(s, 3),
                       theta=round(theta, 3), P_fit_R2=round(float(r2), 3))]
                 ).to_csv(HERE / "calibrated_coefficients.csv", index=False)
    print("wrote figures/ + per_day_statistics.csv + calibrated_coefficients.csv")


if __name__ == "__main__":
    main()
