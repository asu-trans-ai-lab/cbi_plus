# -*- coding: utf-8 -*-
"""cbi_dashboard — one self-contained PAQ/QVDF dashboard per corridor run.

The I-10 W Phoenix / AZ I-17 dashboard, reproduced for ANY corridor the
pipeline has processed (PeMS compact JSON, INRIX RITIS folder, or the
TrafficFlowBench adapter): date -> segment -> queue-object hierarchy,
space-time contour, v(t) + QVDF quartic reconstruction, PAQ quadratic-vs-
quartic queue-shape fits, queue-object Gantt with Isolated/Overlap/Spillback
relations, parameter table, computed spillback note. Vanilla canvas JS —
no plotly, no CDN, opens offline.

CLI (mirrors corridor_workflow's source arguments):

  python -m cbi_pipeline.cbi_dashboard --corridor 10-E --source pems \
      --pems-path benchmarks/I-10/link_performance.json \
      --run outputs/benchmarks/10-E -o outputs/dashboards/I-10E.html

  python -m cbi_pipeline.cbi_dashboard --corridor I-395_NB --source inrix \
      --inrix-folder <RITIS folder> \
      --run outputs/nvta/I-395_NB -o outputs/dashboards/I-395_NB.html

The HTML template is shared with gui4gmns' renderers/tfb_paq_dashboard.py
(kept in sync by hand; the template is display-only).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import io_unified
from .schemas import PERIOD_SLICE_BOUNDS

PSTART = {p: h[0] for p, h in PERIOD_SLICE_BOUNDS.items()}


# ------------------------------------------------------------------ shape fits
def paq_fits(v: np.ndarray, t0: int, t3: int, v_c: float) -> dict:
    """Newell quadratic vs QVDF quartic on the instantaneous speed-deficit
    queue proxy (both shapes zero at T0/T3, single interior peak)."""
    seg = v[t0:t3 + 1].astype(float)
    ok = np.isfinite(seg)
    if ok.sum() < 4:
        return {}
    d = np.where(ok, np.clip(v_c - seg, 0, None), np.nan)
    n = len(seg)
    t = np.arange(n, dtype=float)
    T3 = float(n - 1)
    shapes = {"quad": t * (T3 - t), "quartic": 0.25 * t**2 * (t - T3)**2}
    out = {}
    m = np.isfinite(d)
    dm = d[m]
    ss = float(((dm - dm.mean())**2).sum())
    for name, F in shapes.items():
        Fm = F[m]
        den = float(Fm @ Fm)
        if den <= 0:
            continue
        a = float(dm @ Fm) / den
        r = dm - a * Fm
        out[f"{name}_scale"] = round(a, 6)
        out[f"{name}_r2"] = round(1 - float(r @ r) / ss, 3) if ss > 0 else None
    return out


def relations(eps_day: list, fields: dict) -> None:
    """Isolated / Overlap / Spillback vs the upstream neighbor's episodes."""
    by_row: dict = {}
    for e in eps_day:
        by_row.setdefault(e["row"], []).append(e)
    for e in eps_day:
        rel = "Isolated"
        for u in by_row.get(e["row"] - 1, []):
            if not (e["t3i"] < u["t0i"] or u["t3i"] < e["t0i"]):
                rel = "Overlap"
                vup = fields[e["date"]][e["row"] - 1][e["t2i"]]
                if vup is not None and vup < e["v_c"]:
                    rel = "Spillback"
                break
        e["rel"] = rel


# ------------------------------------------------------------------ build
def load_long(source: str, corridor: str, pems_path=None, inrix_folder=None,
              s3_prior="cbi_default") -> pd.DataFrame:
    if source == "inrix":
        df = io_unified.load_inrix_folder(Path(inrix_folder), s3_prior=s3_prior)
    else:
        df = io_unified.load_pems(path=Path(pems_path))
        df = df[df["corridor"] == corridor]
    if df.empty:
        raise SystemExit(f"no rows for corridor {corridor!r} from {source}")
    return df


def build(corridor: str, run_dir: Path, df: pd.DataFrame, out_html: Path):
    df = df.copy()
    df["date"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d")
    df["tod"] = (pd.to_datetime(df["datetime"]).dt.hour * 12
                 + pd.to_datetime(df["datetime"]).dt.minute // 5)
    order = (df.groupby("sensor_uid")["road_order"].first()
               .sort_values().index.tolist())
    row_of = {s: i for i, s in enumerate(order)}
    ro = df.groupby("sensor_uid")["road_order"].first()
    lanes = df.groupby("sensor_uid")["lanes"].first()
    # On the INRIX path road_order is a TMC SEQUENCE, not a milepost —
    # labeling it "MP" and differencing it for spillback miles was wrong
    # (RITIS-engineer review, SIM-R5). Build cumulative mileposts from
    # per-segment lengths instead.
    src = str(df["source_format"].iloc[0]) if "source_format" in df.columns else ""
    if src.startswith("inrix") and "length_mi" in df.columns:
        seg_len = df.groupby("sensor_uid")["length_mi"].first()
        mp_val, cum = {}, 0.0
        for s in order:
            mp_val[s] = round(cum, 2)
            step = float(seg_len.get(s, np.nan))
            cum += step if np.isfinite(step) else 0.0
    else:
        mp_val = {s: round(float(ro[s]), 2) for s in order}
    meta = [{"sensor": s.split("::")[-1], "mp": mp_val[s],
             "lanes": int(lanes[s]) if np.isfinite(lanes.get(s, np.nan)) else None}
            for s in order]

    dates = sorted(df["date"].unique())
    fields = {}
    piv = df.pivot_table(index=["date", "sensor_uid"], columns="tod",
                         values="speed_mph", aggfunc="mean")
    for date in dates:
        day = []
        for s in order:
            try:
                r = piv.loc[(date, s)]
                day.append([None if not np.isfinite(r.get(t, np.nan))
                            else int(round(r.get(t))) for t in range(288)])
            except KeyError:
                day.append([None] * 288)
        fields[date] = day

    v4 = pd.read_csv(run_dir / "stage4_verification" / "stage4_verification.csv")
    v5p = run_dir / "stage5_verification" / "stage5_qvdf_verification.csv"
    v5k = {}
    if v5p.exists():
        v5 = pd.read_csv(v5p)
        v5k = {(r.sensor_uid, str(r.date), r.period): r for r in v5.itertuples()}

    episodes = []
    for r in v4.itertuples():
        if r.sensor_uid not in row_of:
            continue
        p0 = PSTART.get(r.period, 0) * 12
        date = str(r.date)
        if date not in fields:
            continue
        ep = dict(sensor=r.sensor_uid.split("::")[-1], row=row_of[r.sensor_uid],
                  date=date, period=r.period,
                  t0i=p0 + int(r.t0_idx), t2i=p0 + int(r.t2_idx),
                  t3i=p0 + int(r.t3_idx),
                  P=round(float(r.P_min)), vt2=round(float(r.v_t2_mph), 1),
                  v_c=round(float(r.v_c_prior_mph), 1),
                  mu=None if not np.isfinite(r.mu_obs_vphpl) else round(float(r.mu_obs_vphpl)),
                  cap=round(float(r.capacity_calibrated_vphpl)),
                  d0i=None if not np.isfinite(r.discharge_start_idx) else p0 + int(r.discharge_start_idx),
                  d1i=None if not np.isfinite(r.discharge_end_idx) else p0 + int(r.discharge_end_idx))
        q = v5k.get((r.sensor_uid, date, r.period))
        if q is not None:
            ep.update(Qn=round(float(q.Q_n), 3), Qcp=round(float(q.Q_cp), 4),
                      DoC=round(float(q.R1_D_over_C), 2),
                      Qmu=None if not np.isfinite(q.Q_mu_vphpl) else round(float(q.Q_mu_vphpl)),
                      Qg=None if not np.isfinite(q.Q_gamma) else round(float(q.Q_gamma), 4),
                      t0h=round(float(q.t0_hat_hour), 3), t3h=round(float(q.t3_hat_hour), 3),
                      mape=None if not np.isfinite(q.v_t_MAPE_pct) else round(float(q.v_t_MAPE_pct), 1))
        varr = np.array([np.nan if v is None else v
                         for v in fields[date][ep["row"]]], float)
        ep.update(paq_fits(varr, ep["t0i"], ep["t3i"], ep["v_c"]))
        episodes.append(ep)

    for date in dates:
        relations([e for e in episodes if e["date"] == date], fields)

    payload = dict(corridor=corridor, dates=dates, sensors=meta, fields=fields,
                   episodes=episodes,
                   source="CBI+ pipeline run: " + str(run_dir))
    html = _template(corridor)
    html = html.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    print(f"wrote {out_html}  ({out_html.stat().st_size/1e6:.1f} MB, "
          f"{len(episodes)} episodes, {len(dates)} days, {len(order)} sensors)")


def _template(corridor: str) -> str:
    """Load the shared display template (synced copy of gui4gmns' generator)."""
    tpl = (Path(__file__).parent / "cbi_dashboard_template.html").read_text(encoding="utf-8")
    return tpl.replace("__TITLE__",
                       f"{corridor} — Hierarchical PAQ/QVDF Queue Identification (CBI+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corridor", required=True)
    ap.add_argument("--source", choices=["pems", "inrix"], required=True)
    ap.add_argument("--pems-path", default=None)
    ap.add_argument("--inrix-folder", default=None)
    ap.add_argument("--s3-prior", default="cbi_default")
    ap.add_argument("--run", required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    df = load_long(a.source, a.corridor, a.pems_path, a.inrix_folder, a.s3_prior)
    build(a.corridor, Path(a.run), df, Path(a.out))


if __name__ == "__main__":
    main()
