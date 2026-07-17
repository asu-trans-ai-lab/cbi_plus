# -*- coding:utf-8 -*-
"""QVDF turn-key — quality dashboard figure (gates heatmap + R2 / MAPE / time-series bars)."""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import config as C


def build_dashboard(keys):
    rows, gates = [], []
    for k in keys:
        out = os.path.join(C.OUT_ROOT, k)
        cf = os.path.join(out, "Quality_calibration.csv")
        if not (os.path.exists(cf) and os.path.getsize(cf) > 5):
            continue
        try:
            cal = pd.read_csv(cf); ts = pd.read_csv(os.path.join(out, "Quality_timeseries.csv"))
            g = pd.read_csv(os.path.join(out, "quality_gates.csv"))
        except Exception:
            continue
        if len(cal) == 0:
            continue
        for _, r in cal.iterrows():
            lab = f"{k} {r.period}"
            rows.append(dict(label=lab, step1=r.step1_DC_P_R2, step2=r.step2_P_mag_R2,
                             P_MAPE=r.P_MAPE_pct, vt2_MAPE=r.vt2_MAPE_pct,
                             vt2_within=r.get("vt2_within_tol_pct", float("nan")),
                             smooth=round(ts.smooth_vs_raw_R2.median(), 3)))
        for _, r in g.iterrows():
            gates.append(dict(label=f"{k} {r.period}", gate=r.gate, ok=1 if r.status == "PASS" else 0))
    if not rows:
        return
    df = pd.DataFrame(rows); x = np.arange(len(df)); w = 0.4
    fig = plt.figure(figsize=(max(13, len(df) * 0.7), 10))

    ax1 = fig.add_subplot(2, 2, 1)
    piv = pd.DataFrame(gates).pivot_table(index="label", columns="gate", values="ok")
    ax1.imshow(piv.values, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax1.set_xticks(range(len(piv.columns))); ax1.set_xticklabels(piv.columns, rotation=40, ha="right", fontsize=7)
    ax1.set_yticks(range(len(piv.index))); ax1.set_yticklabels(piv.index, fontsize=7)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            ax1.text(j, i, "P" if v == 1 else ("F" if v == 0 else ""), ha="center", va="center", fontsize=6)
    ax1.set_title("Quality gates  (green=PASS, red=FAIL)")

    ax2 = fig.add_subplot(2, 2, 2)
    ax2.bar(x - w/2, df.step1, w, label="D/C->P R2"); ax2.bar(x + w/2, df.step2, w, label="P->magnitude R2")
    ax2.axhline(0.5, color="gray", ls=":", lw=1); ax2.axhline(0, color="k", lw=0.5)
    ax2.set_xticks(x); ax2.set_xticklabels(df.label, rotation=90, fontsize=6); ax2.set_ylim(-1.05, 1.05)
    ax2.set_title("Calibration fit R2 (higher better; dotted=0.5 gate)"); ax2.legend(fontsize=7)

    ax3 = fig.add_subplot(2, 2, 3)
    ax3.bar(x - w/2, df.P_MAPE, w, label="P MAPE %"); ax3.bar(x + w/2, df.vt2_MAPE, w, label="V_t2 MAPE %")
    ax3.axhline(30, color="red", ls=":", lw=1)
    ax3.set_xticks(x); ax3.set_xticklabels(df.label, rotation=90, fontsize=6); ax3.set_ylabel("MAPE %")
    a3b = ax3.twinx()                                          # V_t2 GATE per corridor (right axis)
    a3b.plot(x, df.vt2_within, "g-^", ms=4, lw=1.4, label="V_t2 within 10 mph %")
    a3b.axhline(70, color="green", ls=":", lw=1); a3b.set_ylim(0, 105)
    a3b.set_ylabel("V_t2 within-tol %", color="g"); a3b.tick_params(axis="y", labelcolor="g")
    l1, la1 = ax3.get_legend_handles_labels(); l2, la2 = a3b.get_legend_handles_labels()
    ax3.legend(l1 + l2, la1 + la2, fontsize=7, loc="upper left")
    ax3.set_title("Model accuracy: P/V_t2 MAPE (bars) + V_t2 gate % links<10 mph (green; 70% gate)")

    ax4 = fig.add_subplot(2, 2, 4)
    ax4.bar(x, df.smooth, w * 1.5, label="smoothed-vs-raw R2", color="tab:blue")
    ax4.axhline(0.9, color="gray", ls=":", lw=1)
    ax4.set_xticks(x); ax4.set_xticklabels(df.label, rotation=90, fontsize=6); ax4.set_ylim(0.8, 1.01)
    ax4.set_title("Avg-weekday smoothing fidelity (Stage I; day-to-day is Stage II)"); ax4.legend(fontsize=7)

    fig.suptitle("QVDF Stage-I (average-weekday) calibration quality dashboard", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    path = os.path.join(C.OUT_ROOT, "_QUALITY_DASHBOARD.png")
    fig.savefig(path, dpi=130); plt.close(fig)
    print(f"wrote {path}")
