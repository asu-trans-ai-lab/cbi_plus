"""
stage3_fd_robust.py — robust regime-separated FD fit (Layer 3).

Three regimes: free_flow / near_capacity / congested.
Huber loss via scipy.optimize.least_squares(loss="huber").
Bootstrap CIs over n_boot resamples.
Physical constraints enforced via box bounds: 0 ≤ q ≤ C, q(v_c) ≈ C.

Output is a drop-in superset of part1_fd_congestion_output.json:
    json["fd"]         — same outer keys as the legacy block
    json["fd_robust"]  — additive: regime fits + bootstrap bands
    json["meta"]       — provenance
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .schemas import stage3_fd_json_skeleton


REGIMES = ("free_flow", "near_capacity", "congested")


# ---------------------------------------------------------------------------
# Six FD models — q(k; params) and v(k; params) closures
# ---------------------------------------------------------------------------
def _model_s3(k, v_f, k_c, m):
    """S3 model: v = v_f / (1 + (k/k_c)^m)^(2/m).  Returns q = k * v."""
    base = 1.0 + (np.maximum(k, 1e-9) / max(k_c, 1e-9)) ** m
    v = v_f / (base ** (2.0 / max(m, 0.1)))
    return v, k * v


def _model_greenshields(k, v_f, k_jam):
    v = np.clip(v_f * (1.0 - k / max(k_jam, 1e-9)), 0.0, v_f)
    return v, k * v


def _model_newell(k, v_f, k_jam, alpha):
    v = v_f * (1.0 - np.exp(-alpha * (1.0 / max(k, 1e-9) - 1.0 / max(k_jam, 1e-9))))
    v = np.clip(v, 0.0, v_f)
    return v, k * v


def _model_underwood(k, v_f, k_c):
    v = v_f * np.exp(-k / max(k_c, 1e-9))
    return v, k * v


def _model_van_aerde(k, v_f, k_c, c1, c2):
    # Simplified Van Aerde: v(k) = v_f * (1 - (k/k_jam))/(1 + c1 k + c2 k^2)
    denom = 1.0 + c1 * k + c2 * k * k
    v = v_f * (1.0 - k / (max(k_c, 1e-9) * 4.0)) / np.maximum(denom, 1e-6)
    v = np.clip(v, 0.0, v_f)
    return v, k * v


def _model_lcm(k, v_f, k_c, beta):
    # Logistic-capacity model
    v = v_f / (1.0 + (k / max(k_c, 1e-9)) ** beta)
    return v, k * v


MODELS = {
    "S3":           dict(fn=_model_s3,           params=["v_f", "k_c", "m"],
                         bounds=([20, 10, 1.0], [85, 200, 8.0])),
    "Greenshields": dict(fn=_model_greenshields, params=["v_f", "k_jam"],
                         bounds=([20, 50], [85, 300])),
    "Newell":       dict(fn=_model_newell,       params=["v_f", "k_jam", "alpha"],
                         bounds=([20, 50, 0.01], [85, 300, 5.0])),
    "Underwood":    dict(fn=_model_underwood,    params=["v_f", "k_c"],
                         bounds=([20, 10], [85, 200])),
    "VanAerde":     dict(fn=_model_van_aerde,    params=["v_f", "k_c", "c1", "c2"],
                         bounds=([20, 10, 0.0, 0.0], [85, 200, 1.0, 1.0])),
    "LCM":          dict(fn=_model_lcm,          params=["v_f", "k_c", "beta"],
                         bounds=([20, 10, 1.0], [85, 200, 8.0])),
}


# ---------------------------------------------------------------------------
# Regime split
# ---------------------------------------------------------------------------
def split_regimes(df: pd.DataFrame,
                  v_c: float, k_c: float,
                  v_f: float) -> dict:
    """Return three masks over df: free_flow / near_capacity / congested."""
    _spd = "speed_mph" if "speed_mph" in df.columns else "speed_mph_clean"
    v = df[_spd].to_numpy(dtype=float)
    k = df["density_vpm"].to_numpy(dtype=float)
    mask_free = (v >= 0.95 * v_f) & (k < 0.6 * k_c)
    mask_near = (k >= 0.6 * k_c) & (k <= 1.2 * k_c)
    mask_cong = (k > 1.2 * k_c) | (v < v_c)
    return dict(free_flow=mask_free, near_capacity=mask_near, congested=mask_cong)


# ---------------------------------------------------------------------------
# Huber-loss fit
# ---------------------------------------------------------------------------
def _residuals(params, model_fn, k_obs, q_obs):
    _, q_pred = model_fn(k_obs, *params)
    return q_pred - q_obs


def _normalize_model_name(model_name: str) -> str:
    """Case-insensitive model lookup with a helpful error."""
    if model_name in MODELS:
        return model_name
    match = {m.lower(): m for m in MODELS}.get(str(model_name).lower())
    if match is None:
        raise KeyError(f"unknown FD model {model_name!r}; available: "
                       f"{sorted(MODELS)}")
    return match


def fit_fd_huber(k: np.ndarray, q: np.ndarray, model_name: str,
                 huber_eps: float = 1.35) -> dict:
    """Fit one model with Huber loss. Returns params, R²/RMSE, and the
    derived curve quantities (capacity_vphpl, k_c_vpm, v_c_mph)."""
    model_name = _normalize_model_name(model_name)
    spec = MODELS[model_name]
    mask = np.isfinite(k) & np.isfinite(q) & (k > 0) & (q >= 0)
    k_obs = k[mask]
    q_obs = q[mask]
    if len(k_obs) < max(5, len(spec["params"]) + 2):
        return dict(model=model_name, params=None, r_squared=float("nan"),
                    rmse=float("nan"), n_obs=int(mask.sum()))

    # Initial guess: midpoints of bounds
    x0 = [0.5 * (lo + hi) for lo, hi in zip(*spec["bounds"])]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            res = least_squares(
                _residuals, x0,
                args=(spec["fn"], k_obs, q_obs),
                bounds=spec["bounds"],
                loss="huber",
                f_scale=huber_eps,
                max_nfev=2000,
            )
            params = res.x.tolist()
            _, q_pred = spec["fn"](k_obs, *res.x)
            ss_res = float(np.sum((q_obs - q_pred) ** 2))
            ss_tot = float(np.sum((q_obs - np.mean(q_obs)) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
            rmse = float(np.sqrt(ss_res / len(q_obs)))
        except Exception:
            params, r2, rmse = None, float("nan"), float("nan")

    # derived curve quantities — capacity is the CURVE's peak, so hand the
    # caller the peak instead of making everyone re-derive it (found by the
    # 2026-07-08 packaged smoke matrix: every consumer rebuilt the grid)
    cap = k_c = v_c = float("nan")
    if params is not None:
        kk = np.linspace(max(1e-3, np.nanmin(k_obs)), max(np.nanmax(k_obs), 140.0), 800)
        _, qq = spec["fn"](kk, *params)
        i = int(np.nanargmax(qq))
        cap, k_c = float(qq[i]), float(kk[i])
        v_c = cap / k_c if k_c > 0 else float("nan")
    return dict(model=model_name, params=params,
                param_names=spec["params"],
                r_squared=float(r2), rmse=float(rmse),
                capacity_vphpl=cap, k_c_vpm=k_c, v_c_mph=v_c,
                n_obs=int(mask.sum()))


def bootstrap_fd(k: np.ndarray, q: np.ndarray, model_name: str,
                 n_boot: int = 200, seed: int = 42,
                 huber_eps: float = 1.35) -> dict:
    """Naïve resample bootstrap → per-parameter 5/50/95 percentiles."""
    model_name = _normalize_model_name(model_name)
    rng = np.random.default_rng(seed)
    mask = np.isfinite(k) & np.isfinite(q) & (k > 0) & (q >= 0)
    k_obs = k[mask]
    q_obs = q[mask]
    n = len(k_obs)
    if n < 20 or n_boot < 1:
        return {}
    n_params = len(MODELS[model_name]["params"])
    samples = np.full((n_boot, n_params), np.nan)
    capacities = np.full(n_boot, np.nan)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        kb, qb = k_obs[idx], q_obs[idx]
        fit = fit_fd_huber(kb, qb, model_name, huber_eps=huber_eps)
        if fit["params"] is not None:
            samples[b, :] = fit["params"]
            # capacity is max(q_pred) over a fine grid
            grid = np.linspace(1.0, max(150.0, np.nanmax(kb) * 1.1), 200)
            _, qp = MODELS[model_name]["fn"](grid, *fit["params"])
            capacities[b] = float(np.nanmax(qp))
    out = {}
    pnames = MODELS[model_name]["params"]
    for j, name in enumerate(pnames):
        col = samples[:, j]
        col = col[np.isfinite(col)]
        if len(col) >= 10:
            out[name] = [float(np.percentile(col, 5)),
                         float(np.percentile(col, 50)),
                         float(np.percentile(col, 95))]
    cap = capacities[np.isfinite(capacities)]
    if len(cap) >= 10:
        out["capacity_vphpl"] = [float(np.percentile(cap, 5)),
                                 float(np.percentile(cap, 50)),
                                 float(np.percentile(cap, 95))]
    return out


# ---------------------------------------------------------------------------
# Best-of-six selection
# ---------------------------------------------------------------------------
def fit_all_six_models(df: pd.DataFrame, huber_eps: float = 1.35) -> dict:
    """
    Fit all six models on the full (post-QC) sample. Used for the legacy
    `fd` block. Best model = highest combined R².
    """
    k = df["density_vpm"].to_numpy(dtype=float)
    q = df["flow_vph"].to_numpy(dtype=float)
    results = {name: fit_fd_huber(k, q, name, huber_eps=huber_eps) for name in MODELS}
    valid = {n: r for n, r in results.items() if np.isfinite(r.get("r_squared", np.nan))}
    if not valid:
        return dict(all_models=results, best=None)
    best_name = max(valid, key=lambda n: valid[n]["r_squared"])
    return dict(all_models=results, best=best_name)


def fit_regimes(df: pd.DataFrame, v_c: float, k_c: float, v_f: float,
                huber_eps: float = 1.35,
                model_pool: Optional[list] = None) -> dict:
    """Fit best model per regime with Huber loss."""
    pool = model_pool or list(MODELS.keys())
    regimes = split_regimes(df, v_c=v_c, k_c=k_c, v_f=v_f)
    out = {}
    for r_name in REGIMES:
        sub = df[regimes[r_name]]
        if len(sub) < 10:
            out[r_name] = dict(model=None, n_obs=int(len(sub)),
                               r_squared=float("nan"), rmse=float("nan"),
                               params=None)
            continue
        k = sub["density_vpm"].to_numpy()
        q = sub["flow_vph"].to_numpy()
        per_model = {m: fit_fd_huber(k, q, m, huber_eps=huber_eps) for m in pool}
        valid = {m: f for m, f in per_model.items()
                 if np.isfinite(f.get("r_squared", np.nan))}
        if not valid:
            out[r_name] = dict(model=None, n_obs=int(len(sub)),
                               r_squared=float("nan"), rmse=float("nan"),
                               params=None)
        else:
            best = max(valid, key=lambda m: valid[m]["r_squared"])
            out[r_name] = dict(best_model=best, **valid[best],
                               candidates_r2={m: f["r_squared"] for m, f in valid.items()})
    return out


# ---------------------------------------------------------------------------
# Capacity-borrow fallback for speed-only TMC inputs
# ---------------------------------------------------------------------------
def speed_only_fallback(df: pd.DataFrame,
                        corridor_C_prior_vphpl: float = 2000.0,
                        v_f_prior_mph: float = 65.0,
                        v_c_prior_mph: float = 50.0) -> dict:
    """
    For INRIX rows (no volume): fit v(k) shape on a synthetic density grid
    seeded by speed quantiles; borrow capacity from a sibling PeMS link.
    """
    _spd = "speed_mph" if "speed_mph" in df.columns else "speed_mph_clean"
    v = df[_spd].to_numpy(dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 20:
        return dict(model="speed_only_borrow", params=None,
                    r_squared=float("nan"), capacity_vphpl=corridor_C_prior_vphpl,
                    v_f_mph=v_f_prior_mph, v_c_mph=v_c_prior_mph)
    v_f_hat = float(np.percentile(v, 95))
    return dict(model="speed_only_borrow",
                params=dict(v_f_mph=v_f_hat,
                            v_c_mph=v_c_prior_mph,
                            capacity_vphpl=corridor_C_prior_vphpl),
                r_squared=float("nan"),
                capacity_vphpl=corridor_C_prior_vphpl,
                v_f_mph=v_f_hat, v_c_mph=v_c_prior_mph,
                note="INRIX speed-only — capacity borrowed from sibling PeMS link.")


# ---------------------------------------------------------------------------
# Per-sensor orchestrator
# ---------------------------------------------------------------------------
def run_fd_for_sensor(df_sensor: pd.DataFrame,
                      huber_eps: float = 1.35,
                      n_boot: int = 200,
                      corridor_C_prior_vphpl: float = 2000.0) -> dict:
    """
    Fit FD for a single sensor. Branches on `has_volume`:
      - PeMS: full regime fit + bootstrap on best model.
      - INRIX: speed_only_fallback.
    """
    has_vol = bool(df_sensor["has_volume"].iloc[0])
    flow_synth = bool(df_sensor.get("flow_synthetic", pd.Series([False])).iloc[0]) \
        if "flow_synthetic" in df_sensor.columns else False
    source_format = str(df_sensor["source_format"].iloc[0])
    sensor_uid = str(df_sensor["sensor_uid"].iloc[0])
    out = stage3_fd_json_skeleton(sensor_uid, source_format)

    qc_pass = df_sensor[df_sensor.get("qc_pass", 1) == 1] if "qc_pass" in df_sensor.columns else df_sensor
    out["meta"]["n_obs"] = int(len(df_sensor))
    out["meta"]["n_obs_qc_passed"] = int(len(qc_pass))
    out["meta"]["qc_pass_rate"] = float(len(qc_pass) / max(len(df_sensor), 1))
    out["meta"]["has_volume"] = has_vol
    out["meta"]["flow_synthetic"] = flow_synth

    # Fit the full FD whenever flow exists (real OR CBI-synthesized).
    # Fall back only if neither is available.
    flow_available = ("flow_vph" in qc_pass.columns
                      and not qc_pass["flow_vph"].isna().all())
    if not flow_available:
        fb = speed_only_fallback(qc_pass, corridor_C_prior_vphpl=corridor_C_prior_vphpl)
        out["fd"].update({
            "model": fb["model"],
            "free_flow_speed_kph": fb["v_f_mph"] * 1.609,
            "speed_at_capacity_kph": fb["v_c_mph"] * 1.609,
            "capacity_vphpl": fb["capacity_vphpl"],
            "r_squared": fb["r_squared"],
        })
        out["fd_robust"]["regimes"] = {}
        out["fd_robust"]["best_model_overall"] = fb["model"]
        return out

    # PeMS branch — full fit
    all_six = fit_all_six_models(qc_pass, huber_eps=huber_eps)
    best_name = all_six["best"]
    best_fit = all_six["all_models"].get(best_name) if best_name else None

    if best_fit and best_fit["params"]:
        spec = MODELS[best_name]
        # Capacity = max(q) on a fine k-grid
        grid = np.linspace(1.0, 200.0, 400)
        _, qp = spec["fn"](grid, *best_fit["params"])
        capacity = float(np.nanmax(qp))
        v_f = best_fit["params"][0]   # convention: v_f first
        # v_c approximated as v at argmax(q)
        idx = int(np.nanargmax(qp))
        v_c, _ = spec["fn"](np.array([grid[idx]]), *best_fit["params"])
        v_c = float(v_c[0])
        k_c = float(grid[idx])

        out["fd"].update({
            "model": best_name,
            "free_flow_speed_kph": float(v_f * 1.609),
            "speed_at_capacity_kph": float(v_c * 1.609),
            "critical_density_vpk": float(k_c / 1.609),
            "capacity_vphpl": capacity,
            "m_exponent": float(best_fit["params"][2]) if len(best_fit["params"]) > 2 else None,
            "r_squared": float(best_fit["r_squared"]),
        })

        # Regime fits + bootstrap on best model only
        regime_fits = fit_regimes(qc_pass, v_c=v_c, k_c=k_c, v_f=v_f,
                                  huber_eps=huber_eps)
        out["fd_robust"]["regimes"] = regime_fits
        out["fd_robust"]["best_model_overall"] = best_name
        out["fd_robust"]["bootstrap_band"] = bootstrap_fd(
            qc_pass["density_vpm"].to_numpy(),
            qc_pass["flow_vph"].to_numpy(),
            best_name, n_boot=n_boot, huber_eps=huber_eps,
        )
        out["fd_robust"]["n_bootstrap"] = int(n_boot)
        out["fd_robust"]["candidate_models_r2"] = {
            m: f["r_squared"] for m, f in all_six["all_models"].items()
        }
        if flow_synth:
            out["fd_robust"]["note"] = (
                "flow_vph was synthesized via CBI inverse-S3 (DTA.py:661). "
                "An S3 fit will trivially recover the prior; the FD R² is not "
                "an independent goodness-of-fit on this sensor. Use the FD only "
                "to propagate the assumed S3 prior consistently into downstream "
                "stages — μ identification (Stage 4) is where the real check is."
            )

    return out


def run_fd(df_qc: pd.DataFrame,
           n_boot: int = 200,
           huber_eps: float = 1.35,
           corridor_C_prior_vphpl: float = 2000.0) -> dict:
    """Run FD for every sensor in df_qc. Returns {sensor_uid: fd_json}."""
    out = {}
    for sid, grp in df_qc.groupby("sensor_uid", sort=False):
        out[sid] = run_fd_for_sensor(grp, huber_eps=huber_eps, n_boot=n_boot,
                                     corridor_C_prior_vphpl=corridor_C_prior_vphpl)
    return out


def write_stage3(fd_by_sensor: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for sid, payload in fd_by_sensor.items():
        safe = sid.replace(":", "_").replace("/", "_")
        with open(out_dir / f"{safe}.json", "w") as f:
            json.dump(payload, f, indent=2, default=float)
    # Aggregated CSV
    rows = []
    for sid, p in fd_by_sensor.items():
        rows.append({
            "sensor_uid": sid,
            "model": p["fd"]["model"],
            "v_f_kph": p["fd"]["free_flow_speed_kph"],
            "v_c_kph": p["fd"]["speed_at_capacity_kph"],
            "capacity_vphpl": p["fd"]["capacity_vphpl"],
            "r_squared": p["fd"]["r_squared"],
            "qc_pass_rate": p["meta"]["qc_pass_rate"],
            "has_volume": p["meta"]["has_volume"],
            "n_obs": p["meta"]["n_obs_qc_passed"],
        })
    pd.DataFrame(rows).to_csv(out_dir / "stage3_fd_summary.csv", index=False)
