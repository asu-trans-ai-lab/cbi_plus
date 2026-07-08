# -*- coding: utf-8 -*-
"""Polynomial-Arrival-Queue (PAQ) repo — reproduction on ITS OWN data.

The PAQ repo ships a 22-detector freeway corridor (Dataset 1: daily
Speed_04XX.xlsx files, April days 01-12, long format Time x Postmile x
AggSpeed) and calibrates a cubic polynomial arrival-queue model on the
corridor's PM queue (its Step-2 grid search hardcodes the observed window
t0=13:10 -> t3=19:44 over spatial detectors 5-15).

This script reproduces the repo's core artifacts from that same data:
  1. the corridor space-time speed field (their Step-1 heatmap),
  2. the physical queue-length profile L(t) = miles of corridor below the
     congestion speed threshold (their queue-profile construction),
  3. the polynomial queue-shape calibration on their [t0, t3] window —
     cubic (their model) vs quadratic (Newell) vs quartic (QVDF), with R².

Run:  python reproduce_paq.py         (~1 min)
Outputs: figures/paq_field_and_queue.png, figures/paq_shape_fits.png,
         paq_fit_results.csv
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

V_THRESH = 40.0            # queue threshold (mph) on AggSpeed
T0, T3 = "13:10", "19:44"  # the repo's own Step-2 window
SPATIAL = (5, 15)          # the repo's own detector index window


def load_day(f: Path) -> pd.DataFrame:
    df = pd.read_excel(f)
    df = df.rename(columns={"Postmile (Abs)": "pm", "AggSpeed": "v"})
    df["t"] = pd.to_datetime(df["Time"].astype(str)).dt.strftime("%H:%M")
    return df[["t", "pm", "v"]].dropna()


def field_of(df: pd.DataFrame):
    piv = df.pivot_table(index="pm", columns="t", values="v", aggfunc="mean")
    return piv.sort_index()


def queue_profile(piv: pd.DataFrame) -> pd.Series:
    """physical queue length (miles of corridor below V_THRESH) per time bin"""
    pms = piv.index.to_numpy()
    seg = np.gradient(pms)                       # local spacing (mi)
    below = (piv.to_numpy() < V_THRESH)
    return pd.Series((below * seg[:, None]).sum(axis=0), index=piv.columns)


def episode_span(q: pd.Series) -> tuple:
    """the queue's own zero-to-zero span around its peak (PAQ requires
    Q(t0)=Q(t3)=0; the repo's fixed window starts mid-queue)."""
    a = q.to_numpy(dtype=float)
    pk = int(np.nanargmax(a))
    i0 = pk
    while i0 > 0 and a[i0 - 1] > 0.3:
        i0 -= 1
    i1 = pk
    while i1 < len(a) - 1 and a[i1 + 1] > 0.3:
        i1 += 1
    return i0, i1


def shape_fits(q: pd.Series, i0: int, i1: int) -> dict:
    """cubic (their PAQ), quadratic (Newell), quartic (QVDF) on the episode."""
    win = q.to_numpy(dtype=float)[i0:i1 + 1]
    n = len(win)
    t = np.arange(n, dtype=float)
    T = float(n - 1)
    trap = np.minimum(np.minimum(t / max(0.25 * T, 1), 1.0),
                      (T - t) / max(0.25 * T, 1))       # rise-plateau-fall (25/50/25)
    shapes = {
        "quadratic": t * (T - t),
        "cubic": t * (T - t) * (T / 2 + 0.35 * T - t),   # skewed cubic (rate form int.)
        "quartic": 0.25 * t**2 * (t - T)**2,
        "trapezoid": np.clip(trap, 0, None),
    }
    ss = float(((win - win.mean())**2).sum())
    out = {}
    for name, F in shapes.items():
        den = float(F @ F)
        if den <= 0:
            continue
        a = float(win @ F) / den
        r = win - a * F
        out[name] = dict(scale=a, r2=(1 - float(r @ r) / ss) if ss > 0 else np.nan)
    out["_win"] = win
    out["_shapes"] = shapes
    return out


def main():
    files = sorted((HERE / "data" / "Dataset 1" / "Speed").glob("Speed_*.xlsx"))
    print(f"{len(files)} daily speed files")
    fields = {f.stem.split("_")[1]: field_of(load_day(f)) for f in files}

    # pick the day with the largest PM-window queue (their case day analog)
    qmax_day = max(fields, key=lambda d: queue_profile(fields[d]).max())
    piv = fields[qmax_day]
    q = queue_profile(piv)
    i0e, i1e = episode_span(q)
    fits = shape_fits(q, i0e, i1e)
    print(f"day 04{qmax_day[-2:]}: peak queue "
          f"{q.max():.2f} mi | R² quad={fits['quadratic']['r2']:.3f} "
          f"cubic={fits['cubic']['r2']:.3f} quartic={fits['quartic']['r2']:.3f} "
          f"trapezoid={fits['trapezoid']['r2']:.3f}")

    # ---- figure 1: field + queue profile
    fig, ax = plt.subplots(2, 1, figsize=(11, 7.4), height_ratios=[2, 1], sharex=False)
    tcols = list(piv.columns)
    im = ax[0].imshow(piv.to_numpy(), aspect="auto", cmap="RdYlGn", vmin=10, vmax=70,
                      extent=[0, len(tcols), float(piv.index.max()), float(piv.index.min())])
    fig.colorbar(im, ax=ax[0], label="speed (mph)")
    xticks = np.linspace(0, len(tcols) - 1, 8).astype(int)
    ax[0].set_xticks(xticks); ax[0].set_xticklabels([tcols[i] for i in xticks])
    ax[0].set_ylabel("postmile (Abs)"); ax[0].set_title(
        f"PAQ Dataset 1 — 22-detector corridor space-time speed field (day 04{qmax_day[-2:]})")
    ax[1].plot(range(len(q)), q.to_numpy(), c="#1d232b")
    i0, i1 = tcols.index(min(c for c in tcols if c >= T0)), tcols.index(max(c for c in tcols if c <= T3))
    ax[1].axvspan(i0, i1, color="#2563eb", alpha=.12, label=f"repo window {T0}–{T3}")
    ax[1].set_xticks(xticks); ax[1].set_xticklabels([tcols[i] for i in xticks])
    ax[1].set_ylabel("queue length (mi < %d mph)" % V_THRESH); ax[1].legend()
    fig.tight_layout(); fig.savefig(FIG / "paq_field_and_queue.png", dpi=140); plt.close(fig)

    # ---- figure 2: shape fits on the repo window
    tcols2 = list(q.index); tcols_ep = (tcols2[i0e], tcols2[i1e])
    win = fits["_win"]; t = np.arange(len(win))
    fig, ax = plt.subplots(figsize=(9.4, 5))
    ax.plot(t, win, "k-", lw=2, label="observed queue length")
    for name, col in (("quadratic", "#2f9e5e"), ("cubic", "#2563eb"), ("quartic", "#b3261e"), ("trapezoid", "#c07a12")):
        F = fits["_shapes"][name]
        ax.plot(t, fits[name]["scale"] * F, "--", c=col, lw=2,
                label=f"{name} (R²={fits[name]['r2']:.3f})")
    ax.set_xlabel(f"5-min bins from episode onset (t0={tcols_ep[0]}, t3={tcols_ep[1]})")
    ax.set_ylabel("physical queue length (mi)")
    ax.set_title(f"PAQ shape family on the queue episode [{tcols_ep[0]}, {tcols_ep[1]}], day 04{qmax_day[-2:]}")
    ax.legend()
    fig.tight_layout(); fig.savefig(FIG / "paq_shape_fits.png", dpi=140); plt.close(fig)

    rows = []
    for d2, piv2 in fields.items():
        q2 = queue_profile(piv2)
        if q2.max() < 1.0:
            continue
        a0, a1 = episode_span(q2)
        f2 = shape_fits(q2, a0, a1)
        rows.append(dict(day=f"04{d2[-2:]}", peak_queue_mi=round(float(q2.max()), 2),
                         episode=f"{list(q2.index)[a0]}-{list(q2.index)[a1]}",
                         r2_quadratic=round(f2["quadratic"]["r2"], 3),
                         r2_cubic=round(f2["cubic"]["r2"], 3),
                         r2_quartic=round(f2["quartic"]["r2"], 3),
                         r2_trapezoid=round(f2["trapezoid"]["r2"], 3)))
    pd.DataFrame(rows).to_csv(HERE / "paq_fit_results.csv", index=False)
    best = pd.DataFrame(rows)[["r2_quadratic", "r2_cubic", "r2_quartic", "r2_trapezoid"]].median()
    print("median R2 across %d congested days:" % len(rows), best.round(3).to_dict())
    print("wrote figures/ + paq_fit_results.csv")


if __name__ == "__main__":
    main()
