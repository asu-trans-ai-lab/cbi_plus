# -*- coding:utf-8 -*-
# Reproduce QVDF paper (Zhou, Cheng, Wu et al. 2022, Multimodal Transportation)
# Section 5 case study 1: I-10 corridor, 4 detectors (139, 84, 78, 137).
# Reproduces Fig 8-17 and Tables 5-8 from the paper's own computed data.
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(OUT, "figures")
os.makedirs(FIG, exist_ok=True)

DETS = [139, 84, 78, 137]          # paper panel order (a,b,c,d)
WD = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
      4: "Friday", 5: "Saturday", 6: "Sunday"}

raw = pd.read_csv(os.path.join(R, "corridor_measurement_I10.csv.gz"))
day = pd.read_csv(os.path.join(R, "fd_corridor_measurement_I10_training_set_per_day.csv"))
wk = pd.read_csv(os.path.join(R, "fd_corridor_measurement_I10_training_set.csv"))
tdv = pd.read_csv(os.path.join(R, "td_speed_fd_corridor_measurement_I10_training_set.csv"))
obs = pd.read_csv(os.path.join(R, "corridor_pivot_wd_spd_I10.csv"))

def s3_speed(k, vf, kc, m):
    return vf / np.power(1 + np.power(k / kc, m), 2.0 / m)

# per-detector calibrated params (unique)
P = {d: wk[wk.link_id == d].iloc[0] for d in DETS}

# =====================================================================
# Table 5 — FD parameters
# =====================================================================
t5 = wk.groupby("link_id").agg(
    ultimate_capacity=("ultimate_capacity", "mean"),
    speed_at_capacity=("critical_speed", "mean"),
    critical_density=("critical_density", "mean"),
    free_flow_speed=("free_flow_speed", "mean"),
    m=("flatness_of_curve", "mean")).reindex(DETS).round(1)
t5.to_csv(os.path.join(OUT, "Table5_FD_parameters.csv"))

# =====================================================================
# Fig 8 — Volume-speed fundamental diagram (4 detectors)
# =====================================================================
fig, axes = plt.subplots(2, 2, figsize=(11, 8))
for ax, d, lab in zip(axes.flat, DETS, "abcd"):
    g = raw[raw.link_id == d]
    vol = g["hourly_volume_per_lane"] if "hourly_volume_per_lane" in g else g["volume_per_lane"] * 4
    ax.scatter(vol, g["speed"], s=3, c="k", alpha=0.25, label="Data")
    vf, kc, m = P[d].free_flow_speed, P[d].critical_density, P[d].flatness_of_curve
    kk = np.linspace(0.1, 220, 400)
    vv = s3_speed(kk, vf, kc, m)
    ax.plot(kk * vv, vv, "b--", lw=1.8, label="Estimated curve")
    ax.set_xlim(0, 2000); ax.set_ylim(0, 80)
    ax.set_xlabel("Volume (vehicles/hour/lane)"); ax.set_ylabel("Speed (mile/hour)")
    ax.set_title(f"({lab}) Volume-speed fundamental diagram, ID: {d}")
    ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(FIG, "Fig8_FD_volume_speed.png"), dpi=140); plt.close(fig)

# =====================================================================
# Fig 9 — distributions of P (P>0), inflow demand, D/C, QDF
# =====================================================================
cong = day[day["b_congestion_duration"] > 0]   # P>0 (congested) days, as in the paper
fig, axes = plt.subplots(2, 2, figsize=(11, 8))
specs = [("b_congestion_duration", "Congestion duration (hours)", cong),
         ("demand", "Inflow demand (vehicles/lane)", cong),
         ("demand_over_capacity", "D/C ratio", cong),
         ("qdf", "Queue demand factor (QDF)", cong)]
for ax, (col, xlab, src) in zip(axes.flat, specs):
    vals = src[col].dropna()
    ax.hist(vals, bins=12, color="white", edgecolor="black", weights=np.ones(len(vals)) / len(vals))
    ax.set_xlabel(f"{xlab}\nMean value = {vals.mean():.2f}")
    ax.set_ylabel("Frequency")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y*100:.0f}%"))
fig.suptitle("Fig. 9. Distributions of congestion duration, inflow demand, D/C ratio, and QDF (7:00-21:00)")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "Fig9_distributions.png"), dpi=140); plt.close(fig)

# =====================================================================
# Table 6 — congestion statistics
# =====================================================================
rows = []
for d in DETS:
    g = day[day.link_id == d]
    ndays = len(g); npos = int((g.b_congestion_duration > 0).sum())
    avgP = g.loc[g.b_congestion_duration > 0, "b_congestion_duration"].mean()
    rows.append([d, ndays, npos, f"{npos/ndays*100:.0f}%", f"{avgP:.2f} h"])
t6 = pd.DataFrame(rows, columns=["Detector", "valid_days", "days_P>0", "ratio_congested", "avg_duration_P>0"])
tot_days = t6.valid_days.sum(); tot_pos = t6["days_P>0"].sum()
t6.loc[len(t6)] = ["Total", tot_days, tot_pos, f"{tot_pos/tot_days*100:.0f}%",
                   f"{day.loc[day.b_congestion_duration>0,'b_congestion_duration'].mean():.2f} h"]
t6.to_csv(os.path.join(OUT, "Table6_congestion_stats.csv"), index=False)

# =====================================================================
# Table 7 — calibrated coefficients
# =====================================================================
t7 = pd.DataFrame([[d, P[d].f_d, P[d].nn, P[d].f_p, P[d].ss, P[d].cd_alpha, P[d].cd_beta] for d in DETS],
                  columns=["Detector", "f_d", "n", "f_p", "s", "alpha", "beta"]).round(4)
t7.to_csv(os.path.join(OUT, "Table7_calibrated_coeffs.csv"), index=False)

# =====================================================================
# Fig 10 / 11 / 12 — calibration scatters with curves
# =====================================================================
def mean_at(xvals, yvals, key):
    df = pd.DataFrame({"x": xvals, "y": yvals, "k": key})
    return df.groupby("k").agg(x=("x", "mean"), y=("y", "mean")).reset_index()

# Fig 10: D/C vs P
fig, axes = plt.subplots(2, 2, figsize=(11, 8))
for ax, d, lab in zip(axes.flat, DETS, "abcd"):
    g = day[(day.link_id == d) & (day.b_congestion_duration > 0)]
    dc, p = g.demand_over_capacity.values, g.b_congestion_duration.values
    ax.scatter(dc, p, s=8, c="k", label="Data")
    ma = mean_at(dc, p, np.round(p * 4) / 4)        # mean D/C at each P
    ax.scatter(ma.y * 0 + ma.x, ma.y, facecolors="none", edgecolors="r", s=40, label="Mean value at same P")
    xr = np.linspace(0, dc.max(), 100)
    ax.plot(xr, P[d].f_d * xr ** P[d].nn, "b--", lw=1.8, label="Estimated curve")
    ax.set_xlabel("D/C ratio"); ax.set_ylabel("Congestion duration P (hours)")
    ax.set_title(f"({lab}) ID:{d}, $f_d$={P[d].f_d:.4f}, n={P[d].nn:.4f}", fontsize=10)
    ax.legend(fontsize=7)
fig.tight_layout(); fig.savefig(os.path.join(FIG, "Fig10_step1_DC_vs_P.png"), dpi=140); plt.close(fig)

# Fig 11: P vs magnitude of speed reduction
fig, axes = plt.subplots(2, 2, figsize=(11, 8))
for ax, d, lab in zip(axes.flat, DETS, "abcd"):
    g = day[(day.link_id == d) & (day.b_congestion_duration > 0)].copy()
    g["mag"] = g.cut_off_speed / g.v_t2 - 1.0
    p, mag = g.b_congestion_duration.values, g["mag"].values
    ax.scatter(p, mag, s=8, c="k", label="Data")
    ma = mean_at(p, mag, np.round(p * 4) / 4)
    ax.scatter(ma.x, ma.y, facecolors="none", edgecolors="r", s=40, label="Mean value at same P")
    xr = np.linspace(0, p.max(), 100)
    ax.plot(xr, P[d].f_p * xr ** P[d].ss, "b--", lw=1.8, label="Estimated curve")
    ax.set_xlabel("Congestion duration P (hours)"); ax.set_ylabel("Magnitude of speed reduction")
    ax.set_title(f"({lab}) ID:{d}, $f_p$={P[d].f_p:.4f}, s={P[d].ss:.4f}", fontsize=10)
    ax.legend(fontsize=7)
fig.tight_layout(); fig.savefig(os.path.join(FIG, "Fig11_step2_P_vs_magnitude.png"), dpi=140); plt.close(fig)

# Fig 12: D/C vs average speed during congestion
fig, axes = plt.subplots(2, 2, figsize=(11, 8))
for ax, d, lab in zip(axes.flat, DETS, "abcd"):
    g = day[(day.link_id == d) & (day.b_congestion_duration > 0)]
    dc, vbar = g.demand_over_capacity.values, g.cd_mean_speed.values
    ax.scatter(dc, vbar, s=8, c="k", label="Data")
    xr = np.linspace(0, dc.max(), 100)
    vco = P[d].cut_off_speed
    ax.plot(xr, vco / (1 + P[d].cd_alpha * xr ** P[d].cd_beta), "b--", lw=1.8, label="Estimated curve")
    ax.set_xlabel("D/C ratio"); ax.set_ylabel("Mean speed during congestion duration (miles/hour)")
    ax.set_title(f"({lab}) ID:{d}, alpha={P[d].cd_alpha:.3f}, beta={P[d].cd_beta:.3f}", fontsize=10)
    ax.legend(fontsize=7)
fig.tight_layout(); fig.savefig(os.path.join(FIG, "Fig12_DC_vs_avgspeed.png"), dpi=140); plt.close(fig)

# =====================================================================
# Table 8 + Fig 13 — curvature parameter gamma
#   gamma = 64 * mu * (L/uc) * f_p * P^(s-4),  P = f_d*(D/C)^n,  uc = cut_off
# =====================================================================
def gamma_of(d, dc):
    r = P[d]
    p = r.f_d * dc ** r.nn
    mu = r.est_mu if "est_mu" in r and r.est_mu == r.est_mu else r.ultimate_capacity
    return 64.0 * mu * (r.length / r.cut_off_speed) * r.f_p * np.power(p, r.ss - 4.0)

# Table 8: per (detector, weekday). v_t2, v_bar, P, gamma are the ESTIMATED values
# from the calibrated curves at each weekday's mean observed D/C (matches the paper).
rows = []
for d in DETS:
    r = P[d]
    for w in range(7):
        g = day[(day.link_id == d) & (day.weekday == w)]
        if len(g) == 0:
            continue
        dcm = g.demand_over_capacity.mean()
        pm = r.f_d * dcm ** r.nn                                  # estimated P
        vt2m = r.cut_off_speed / (1 + r.f_p * pm ** r.ss)         # estimated v_t2
        vbarm = r.cut_off_speed / (1 + r.cd_alpha * dcm ** r.cd_beta)  # estimated v_bar
        rows.append([d, WD[w], round(dcm, 2), round(pm, 2), round(vt2m, 2),
                     round(vbarm, 2), round(float(gamma_of(d, dcm)), 2)])
t8 = pd.DataFrame(rows, columns=["Detector", "Days_of_week", "Mean_DC", "Mean_P",
                                 "Mean_v_t2", "Mean_v_bar", "gamma"])
t8.to_csv(os.path.join(OUT, "Table8_curvature_gamma.csv"), index=False)

# Fig 13: gamma vs D/C
fig, ax = plt.subplots(figsize=(9, 6))
dcs = np.arange(0.5, 2.0, 0.05)
colors = {78: "tab:blue", 84: "tab:orange", 137: "gray", 139: "gold"}
for d in DETS:
    ax.plot(dcs, [gamma_of(d, x) for x in dcs], "-o", ms=3, color=colors[d],
            label=f"Detector link {d}, Curvature parameter")
# reference fd=1, fp=0.5, n=1, s=4 -> constant
ref = P[139]
gref = 64.0 * (ref.est_mu if ref.est_mu == ref.est_mu else ref.ultimate_capacity) * (ref.length / ref.cut_off_speed) * 0.5
ax.plot(dcs, [gref] * len(dcs), "x-", color="tab:cyan", label="fd=1,fp=0.5,n=1,s=4")
ax.set_xlabel("D/C ratio"); ax.set_ylabel("Curvature parameter $\\gamma$")
ax.set_ylim(0, 2000); ax.legend(fontsize=8); ax.grid(alpha=0.3)
ax.set_title("Fig. 13. Curvature parameter with the change of the D/C ratio.")
fig.tight_layout(); fig.savefig(os.path.join(FIG, "Fig13_gamma_vs_DC.png"), dpi=140); plt.close(fig)

# =====================================================================
# Fig 14-17 — observed vs estimated time-dependent speed (detector 84, Mon-Thu)
# =====================================================================
DET_TD = 84
tcols_est = [c for c in tdv.columns if ":" in c]                       # 07:00:00 ...
tcols_obs = [c for c in obs.columns if "_" in c and c[0].isdigit()]    # 0700_0715 ...
def hhmm(c):
    if ":" in c:
        h, m, *_ = c.split(":"); return int(h) + int(m) / 60.0
    a = c.split("_")[0]; return int(a[:2]) + int(a[2:]) / 60.0
xe = [hhmm(c) for c in tcols_est]; xo = [hhmm(c) for c in tcols_obs]
for i, w in enumerate([0, 1, 2, 3]):
    fig, ax = plt.subplots(figsize=(10, 5))
    er = tdv[(tdv.link_id == DET_TD) & (tdv.weekday == w)]
    orr = obs[(obs.link_id == DET_TD) & (obs.weekday == w)]
    if len(orr):
        ax.plot(xo, orr[tcols_obs].iloc[0].values, "r--s", ms=3, label=f"Observed time-dependent mean speed ({WD[w]})")
    if len(er):
        ax.plot(xe, er[tcols_est].iloc[0].values, "k-o", ms=3, label=f"Estimated time-dependent mean speed ({WD[w]})")
    ax.set_xlim(7, 21); ax.set_ylim(0, 80)
    ax.set_xticks(range(7, 22)); ax.set_xticklabels([f"{h}:00" for h in range(7, 22)], rotation=45, fontsize=8)
    ax.set_ylabel("Mean speed (miles/hour)")
    ax.set_title(f"Fig. {14+i}. Observed vs estimated speed at detector ID {DET_TD} on {WD[w]}.")
    ax.legend(loc="lower center", fontsize=9); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, f"Fig{14+i}_td_speed_{WD[w]}.png"), dpi=140); plt.close(fig)

# =====================================================================
print("=== Table 5 (FD) ===\n", t5.to_string())
print("\n=== Table 7 (calibrated coeffs) ===\n", t7.to_string(index=False))
print("\n=== Table 6 (congestion stats) ===\n", t6.to_string(index=False))
print("\n=== Table 8 head (gamma) ===\n", t8.head(8).to_string(index=False))
print("\n=== Fig 9 means (P>0 days): P=%.2f, demand=%.0f, D/C=%.2f, QDF=%.2f ==="
      % (cong.b_congestion_duration.mean(), cong.demand.mean(),
         cong.demand_over_capacity.mean(), cong.qdf.mean()))
print("wrote figures to", FIG)
