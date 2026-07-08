# -*- coding: utf-8 -*-
"""tensor_tools — low-rank structure of the corridor field (CBI+ tensor line of work).

Integrated verbatim from the CBI+ Tensor Completion hand-off (Zhou, 2026-07-06,
CBIplus_Tensor_Handoff/code/tensor_completion.py). Adds to the pipeline:

  rpca                 Y = L + S: RECURRENT low-rank structure vs sparse NON-RECURRENT
                       anomalies — the computed (not asserted) recurring/incident split.
                       Feed Y as [(sensor x time-of-day) x day].
  price_of_rank        observability curve: how many independent day-patterns the
                       corridor actually has (effective rank, K90, K99).
  low_rank_complete    Soft-Impute matrix completion (fill sparse/masked fields).
  tensor_complete      3-D cube completion (space x time x lane) - borrows strength
                       across lanes; beats per-lane 2-D by ~30% at low CV penetration.
  recurrent_deviation  mean-over-days baseline + per-day deviation energy.
"""
import numpy as np
import pandas as pd

_KMH_TO_MPH = 0.621371


def _unfold(X, n):
    return np.moveaxis(X, n, 0).reshape(X.shape[n], -1)


def _fold(M, n, shape):
    full = [shape[n]] + [shape[i] for i in range(len(shape)) if i != n]
    return np.moveaxis(M.reshape(full), 0, n)


def low_rank_complete(M, mask, rank, iters=200, agg=None, tol=1e-5, lam=None):
    """Low-rank matrix completion by **Soft-Impute** (Mazumder-Hastie-Tibshirani): iteratively fill
    missing entries with the current estimate and apply singular-value soft-thresholding (the proximal
    operator of the nuclear norm) — provably convergent, unlike exact rank-truncation which diverges.
    M: partial matrix, mask: observed cells. agg: optional per-column marginal (mean over rows).
    rank sets the threshold so ~rank components survive. Returns X_hat."""
    mu = float(np.nanmean(M[mask])) if mask.any() else 0.0
    if lam is None:
        s0 = np.linalg.svd(np.where(mask, M, mu), compute_uv=False)
        lam = float(s0[rank]) if len(s0) > rank else float(s0[-1] * 0.5)
    X = np.where(mask, M, mu)
    prev = None
    for _ in range(iters):
        filled = np.where(mask, M, X)                          # fill missing with current estimate
        U, s, Vt = np.linalg.svd(filled, full_matrices=False)
        s_t = np.clip(s - lam, 0, None)                        # SOFT-threshold singular values
        X = (U * s_t) @ Vt
        if agg is not None:                                    # re-impose column marginal (lane case)
            X = X + (agg[None, :] - X.mean(axis=0)[None, :])
            X[mask] = M[mask]
        if prev is not None and np.linalg.norm(X - prev) / (np.linalg.norm(prev) + 1e-12) < tol:
            break
        prev = X.copy()
    return X


def tensor_complete(T, mask, lam=None, iters=120, tol=1e-4, weights=None):
    """Low-rank TENSOR completion of a 3-D cube (space x time x lane) via sum-of-nuclear-norms over
    the mode unfoldings (SiLRTC / HaLRTC style, numpy). Exploits low rank in ALL modes jointly, so it
    borrows strength ACROSS lanes — unlike per-lane matrix completion. mask: observed cells. Returns
    the completed cube."""
    dims = T.shape; N = T.ndim
    w = weights if weights is not None else [1.0 / N] * N
    mu = float(np.nanmean(T[mask])) if mask.any() else 0.0
    X = np.where(mask, T, mu)
    if lam is None:
        s0 = np.linalg.svd(_unfold(X, 0), compute_uv=False)
        lam = float(s0[min(3, len(s0) - 1)])
    prev = None
    for _ in range(iters):
        acc = np.zeros_like(X)
        for n in range(N):
            U, s, Vt = np.linalg.svd(_unfold(X, n), full_matrices=False)
            s_t = np.clip(s - lam * w[n] * N, 0, None)         # soft-threshold each mode
            acc += w[n] * _fold((U * s_t) @ Vt, n, dims)
        X = acc
        X[mask] = T[mask]
        if prev is not None and np.linalg.norm(X - prev) / (np.linalg.norm(prev) + 1e-12) < tol:
            break
        prev = X.copy()
    return X


def rpca(Y, lam=None, mu=None, tol=1e-6, maxiter=120):
    """Robust PCA / Principal Component Pursuit:  Y = L + S + N  via inexact ALM.

    L = low-rank (the RECURRENT structure that repeats across columns/days), S = sparse (NON-RECURRENT
    incident/weather anomalies), N = residual. Feed Y as [space (seg*time) x day] so L's columns are
    the recurrent bottleneck and S flags anomaly cells/days. Pure numpy. Returns (L, S, info)."""
    Y = np.nan_to_num(np.asarray(Y, float))
    m, n = Y.shape
    lam = lam if lam is not None else 1.0 / np.sqrt(max(m, n))
    normF = np.linalg.norm(Y) + 1e-12
    mu = mu if mu is not None else 1.25 / (np.linalg.norm(Y, 2) + 1e-12)
    mu_bar, rho = mu * 1e7, 1.5
    L = np.zeros_like(Y); S = np.zeros_like(Y); Yd = np.zeros_like(Y)
    it = 0
    for it in range(maxiter):
        U, sig, Vt = np.linalg.svd(Y - S + Yd / mu, full_matrices=False)   # SVT -> low rank
        sig_t = np.clip(sig - 1.0 / mu, 0, None)
        L = (U * sig_t) @ Vt
        T = Y - L + Yd / mu                                                # soft-threshold -> sparse
        S = np.sign(T) * np.clip(np.abs(T) - lam / mu, 0, None)
        Z = Y - L - S
        Yd = Yd + mu * Z
        mu = min(mu * rho, mu_bar)
        if np.linalg.norm(Z) / normF < tol:
            break
    rank = int((np.linalg.svd(L, compute_uv=False) > 1e-6 * (np.linalg.norm(L) + 1e-12)).sum())
    info = dict(iters=it + 1, L_rank=rank,
                L_energy=float(np.linalg.norm(L) ** 2 / normF ** 2),
                S_energy=float(np.linalg.norm(S) ** 2 / normF ** 2),
                S_density=float((np.abs(S) > 1e-9).mean()))
    return L, S, info


def price_of_rank(Y):
    """Price-of-Rank / observability curve from the day-unfolding SVD. Returns a DataFrame
    [K, explained] (cumulative energy explained by K components) plus (effective_rank, K90, K99)."""
    Y = np.nan_to_num(np.asarray(Y, float))
    s = np.linalg.svd(Y, compute_uv=False)
    e = s ** 2
    expl = np.cumsum(e) / e.sum()
    eff = float(e.sum() ** 2 / (np.sum(e ** 2) + 1e-12))       # participation-ratio effective rank
    k90 = int(np.searchsorted(expl, 0.90) + 1)
    k99 = int(np.searchsorted(expl, 0.99) + 1)
    df = pd.DataFrame({"K": np.arange(1, len(s) + 1), "explained": expl.round(4)})
    return df, dict(effective_rank=round(eff, 1), K90=k90, K99=k99, n_modes=len(s))


# ------------------------------------------------------------------ projection-completion (lanes)


def recurrent_deviation(T):
    """Split T into the recurrent baseline (mean over days, [seg,time]) and per-day deviation energy.
    Returns (baseline[seg,time], deviation_energy[day])."""
    base = np.nanmean(T, axis=2)
    dev = np.zeros(T.shape[2])
    for d in range(T.shape[2]):
        r = T[:, :, d] - base
        dev[d] = float(np.sqrt(np.nansum(r * r)))
    return base, dev


def space_time_field(df, pos, time, speed, vehicle, n_pos=40, n_time=50):
    """Bin trajectory points into an Eulerian space-time speed field V[position, time] (mean speed per
    cell over all vehicles). Returns (true[n_pos,n_time], rows) where rows has integer (pi, ti) bins +
    speed + vehicle, for fast per-probe re-binning."""
    d = df[[pos, time, speed, vehicle]].dropna().copy()
    y, t = d[pos].to_numpy(float), d[time].to_numpy(float)
    d["pi"] = np.clip(((y - y.min()) / (y.max() - y.min() + 1e-9) * n_pos).astype(int), 0, n_pos - 1)
    d["ti"] = np.clip(((t - t.min()) / (t.max() - t.min() + 1e-9) * n_time).astype(int), 0, n_time - 1)
    d = d.rename(columns={speed: "v", vehicle: "veh"})
    g = d.groupby(["pi", "ti"]).v.mean()
    true = np.full((n_pos, n_time), np.nan)                # nan where NO vehicle visited (unknown)
    idx = g.index.to_frame().to_numpy()
    true[idx[:, 0], idx[:, 1]] = g.to_numpy()
    return true, d[["pi", "ti", "v", "veh"]]


def space_time_lane_tensor(df, pos, time, speed, vehicle, lane, n_pos=30, n_time=40, lanes=None):
    """Build the 3-D queue cube T[position, time, lane] (mean speed per cell) from trajectories, plus
    rows(pi,ti,li,v,veh) for fast per-probe re-binning. Cells with no vehicle stay nan."""
    d = df[[pos, time, speed, vehicle, lane]].dropna().copy()
    lanes = lanes or sorted(int(x) for x in d[lane].unique() if x > 0)
    d = d[d[lane].isin(lanes)]
    li = {l: i for i, l in enumerate(lanes)}
    y, t = d[pos].to_numpy(float), d[time].to_numpy(float)
    d["pi"] = np.clip(((y - y.min()) / (y.max() - y.min() + 1e-9) * n_pos).astype(int), 0, n_pos - 1)
    d["ti"] = np.clip(((t - t.min()) / (t.max() - t.min() + 1e-9) * n_time).astype(int), 0, n_time - 1)
    d["li"] = d[lane].astype(int).map(li)
    d = d.rename(columns={speed: "v", vehicle: "veh"})
    g = d.groupby(["pi", "ti", "li"]).v.mean()
    T = np.full((n_pos, n_time, len(lanes)), np.nan)
    ix = g.index.to_frame().to_numpy()
    T[ix[:, 0], ix[:, 1], ix[:, 2]] = g.to_numpy()
    return T, d[["pi", "ti", "li", "v", "veh"]], lanes


def probe_completion_test(rows, true, penetrations, rank=3, seed=0, n_trials=5):
    """The matrix-completion hypothesis at full scale: reconstruct the space-time speed field from a
    fraction of PROBE (connected) vehicles via low-rank completion. Ground truth = the all-vehicle
    field; recovery is scored on cells that ARE known from all vehicles but were NOT seen by the probe
    subset (the honest held-out set). Returns dict(pen, r2, eff_rank, recon, obs_frac)."""
    full_mask = ~np.isnan(true)                            # cells known from all vehicles
    fill = float(np.nanmean(true))
    s = np.linalg.svd(np.where(full_mask, true, fill), compute_uv=False); e = s ** 2
    eff = float(e.sum() ** 2 / (np.sum(e ** 2) + 1e-12))
    vehicles = np.array(sorted(rows.veh.unique()))
    out = {"pen": list(penetrations), "r2": [], "rmse": [], "obs_frac": [], "eff_rank": round(eff, 2),
           "n_veh": len(vehicles), "recon": None, "true": np.where(full_mask, true, fill),
           "recon_pen": penetrations[len(penetrations) // 2]}
    rng = np.random.default_rng(seed)
    for p in penetrations:
        r2s, rmses, ofs = [], [], []
        for tr in range(n_trials):
            probes = set(rng.choice(vehicles, max(1, int(len(vehicles) * p)), replace=False))
            obs = rows[rows.veh.isin(probes)].groupby(["pi", "ti"]).v.mean()
            M = np.zeros(true.shape); mask = np.zeros(true.shape, bool)
            ix = obs.index.to_frame().to_numpy()
            M[ix[:, 0], ix[:, 1]] = obs.to_numpy(); mask[ix[:, 0], ix[:, 1]] = True
            Xh = low_rank_complete(M, mask, rank=rank)
            score = full_mask & ~mask                     # known-in-full but unseen-by-probe
            if score.sum():
                r2s.append(1 - np.sum((Xh[score] - true[score]) ** 2) /
                           (np.sum((true[score] - true[score].mean()) ** 2) + 1e-9))
                rmses.append(np.sqrt(np.mean((Xh[score] - true[score]) ** 2)))
            ofs.append(mask.sum() / max(full_mask.sum(), 1))
            if abs(p - out["recon_pen"]) < 1e-9 and tr == 0:
                out["recon"] = Xh
        out["r2"].append(round(float(np.mean(r2s)), 3))
        out["rmse"].append(round(float(np.mean(rmses)), 2))
        out["obs_frac"].append(round(float(np.mean(ofs)), 3))
    return out


def lane_field_from_trajectory(csv_path, n_pos=12, n_time=24):
    """Build a TRUE lane-based speed field from NGSIM-format vehicle trajectories (columns include
    'Lane Num', 'Local Y (ft)' longitudinal position, 'Global Time (s)', 'Speed (ft/s)'). Bins into
    lane x (position x time) cells of mean speed (mph). Returns (true[lane, cell], agg[cell], meta),
    where agg is the lane-blind aggregate (what a loop detector sees). Missing lane-cells are filled
    with the lane mean so there is a complete ground truth to validate completion against."""
    d = pd.read_csv(csv_path); d.columns = [c.strip() for c in d.columns]
    lanes = sorted(int(x) for x in d["Lane Num"].dropna().unique() if x > 0)
    d = d[d["Lane Num"].isin(lanes)].copy()
    li = {l: i for i, l in enumerate(lanes)}
    y, t = d["Local Y (ft)"], d["Global Time (s)"]
    d["pos"] = np.clip(((y - y.min()) / (y.max() - y.min() + 1e-9) * n_pos).astype(int), 0, n_pos - 1)
    d["tb"] = np.clip(((t - t.min()) / (t.max() - t.min() + 1e-9) * n_time).astype(int), 0, n_time - 1)
    d["mph"] = d["Speed (ft/s)"] * 0.681818
    d["li"] = d["Lane Num"].astype(int).map(li)
    g = d.groupby(["li", "pos", "tb"]).mph.mean().reset_index()
    g["cell"] = g.pos * n_time + g.tb
    true = np.full((len(lanes), n_pos * n_time), np.nan)
    true[g.li.to_numpy(), g.cell.to_numpy()] = g.mph.to_numpy()
    for l in range(len(lanes)):
        true[l] = np.where(np.isnan(true[l]), np.nanmean(true[l]), true[l])
    meta = dict(n_lanes=len(lanes), lanes=lanes, n_pos=n_pos, n_time=n_time,
                seg_ft=round(float(y.max() - y.min()), 0), span_min=round(float(t.max() - t.min()) / 60, 1),
                lane_means=[round(float(true[i].mean()), 1) for i in range(len(lanes))],
                n_vehicles=int(d["Vehicle ID"].nunique()))
    return true, true.mean(0), meta


