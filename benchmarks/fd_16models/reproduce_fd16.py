# -*- coding: utf-8 -*-
"""Traffic-Flow-Fundamental-Diagram repo — reproduction on ITS OWN data.

Fits the repo's model suite on the repo's own `data/input_data.csv`
(flow/speed/density scatter) using the repo's OWN solver class
(`calibrate_fundamental_diagram.solve`, vendored here verbatim), regenerates
the flow-density / speed-density comparison figure with S3 as the reference,
and writes the parameter + RMSE table.

Run:  python reproduce_fd16.py          (~1 min)
Outputs: figures/fd_model_comparison.png, model_parameters_rmse.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from calibrate_fundamental_diagram import solve   # the repo's own driver

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

# the repo's own initial solutions (from its __main__)
MODELS = {
    "S3": [70, 35, 3.6],
    "Greenshields": [70, 120],
    "Greenberg": [40, 150],
    "Underwood": [70, 40],
    "NF": [70, 150, 3],
    "GHR_M1": [70, 50],
    "GHR_M2": [70, 120, 2],
    "GHR_M3": [70, 40, 2],
    "KK": [70, 150, 0.25, 0.06, 3.72e-06],
    "Jayakrishnan": [70, 120, 20],
    "MacNicholas": [70, 150, 3, 2],
    "Wang_3PL": [70, 30, 2],
    "Wang_4PL": [70, 5, 30, 2],
    "Wang_5PL": [70, 5, 1, 30, 2],
}


def main():
    data = pd.read_csv(HERE / "data" / "input_data.csv")
    cols = {c.lower(): c for c in data.columns}
    df = pd.DataFrame({"Flow": data[cols.get("flow", "Flow")],
                       "Speed": data[cols.get("speed", "Speed")],
                       "Density": data[cols.get("density", "Density")]}).dropna()
    sv = solve(df)

    rows, fits = [], {}
    for name, x0 in MODELS.items():
        try:
            p = sv.getSolution(name, x0)
            est_speed, est_flow = sv.getEstimatedValue(name, p)
            rmse_q = float(np.sqrt(np.nanmean((est_flow - df["Flow"])**2)))
            rmse_v = float(np.sqrt(np.nanmean((est_speed - df["Speed"])**2)))
            rows.append(dict(model=name, rmse_flow=round(rmse_q, 1),
                             rmse_speed=round(rmse_v, 2),
                             parameters=str([round(float(x), 3) for x in p])))
            fits[name] = (p, est_speed, est_flow)
            print(f"  {name:<14} rmse_flow={rmse_q:7.1f}  rmse_speed={rmse_v:5.2f}")
        except Exception as e:
            rows.append(dict(model=name, rmse_flow=None, rmse_speed=None,
                             parameters=f"FAILED: {type(e).__name__}"))
            print(f"  {name:<14} FAILED ({type(e).__name__}: {e})")

    tbl = pd.DataFrame(rows).sort_values("rmse_flow", na_position="last")
    tbl.to_csv(HERE / "model_parameters_rmse.csv", index=False)

    # comparison figure: k-q and k-v scatter + top-6 fitted curves (S3 highlighted)
    top = [m for m in tbl["model"] if m in fits][:6]
    if "S3" in fits and "S3" not in top:
        top = ["S3"] + top[:5]
    k_axis = np.linspace(1, float(df["Density"].max()), 300)
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    ax[0].scatter(df["Density"], df["Flow"], s=4, c="#c3ccd8", label="observed")
    ax[1].scatter(df["Density"], df["Speed"], s=4, c="#c3ccd8", label="observed")
    for m in top:
        p, _, _ = fits[m]
        dfk = pd.DataFrame({"Flow": np.zeros_like(k_axis),
                            "Speed": np.zeros_like(k_axis), "Density": k_axis})
        svk = solve(dfk)
        v_k, q_k = svk.getEstimatedValue(m, p)
        lw, z = (2.6, 5) if m == "S3" else (1.3, 3)
        ax[0].plot(k_axis, q_k, lw=lw, zorder=z, label=m)
        ax[1].plot(k_axis, v_k, lw=lw, zorder=z, label=m)
    ax[0].set_xlabel("density (veh/mi/ln)"); ax[0].set_ylabel("flow (veh/h/ln)")
    ax[1].set_xlabel("density (veh/mi/ln)"); ax[1].set_ylabel("speed (mph)")
    for a in ax:
        a.legend(fontsize=8)
    ax[0].set_title("flow-density: fitted models (S3 bold)")
    ax[1].set_title("speed-density: fitted models (S3 bold)")
    fig.suptitle("FD model suite on the repo's own input_data.csv (repo's own solver)")
    fig.tight_layout()
    fig.savefig(FIG / "fd_model_comparison.png", dpi=140)
    print(f"wrote {FIG/'fd_model_comparison.png'} + model_parameters_rmse.csv "
          f"({sum(1 for r in rows if r['rmse_flow'] is not None)}/{len(MODELS)} models fitted)")


if __name__ == "__main__":
    main()
