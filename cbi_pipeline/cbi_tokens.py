# -*- coding: utf-8 -*-
"""cbi_tokens — the CBI state compiler: planner-facing analytical vocabulary.

Design principle (2026-07-08 memo):

    CPI/CBI tokens turn traffic-flow diagnostics into a shared engineering
    vocabulary that an agent can detect, explain, validate, and reuse for
    calibration, scenario comparison, reliability analysis, safety-exposure
    assessment, and benefit-cost interpretation.

T0/T1/T2/T3 become planner-readable congestion-state tokens, not hidden
internal variables. Language rule: a CBI token defines the OBSERVED
operational problem and the calibration/benefit target — it never "proves
the project"; only a No-Build/Build comparison does.

Two-dialect note: the memo's markers are T0=pre-breakdown, T1=onset,
T2=worst, T3=recovery. The pipeline's internal episode indices are
t0=onset, t2=worst, t3=recovery. Tokens speak the MEMO dialect; the
mapping is carried on every token (`internal_markers`) and in
docs/CBI_TOKENS.md.

Token families:
  A. state tokens        — CBI_FREE_FLOW ... CBI_RESIDUAL_CONGESTION
  B. time-marker tokens  — T0_PRE_BREAKDOWN, T1_ONSET, T2_WORST_STATE,
                           T3_RECOVERY, T4_RESIDUAL_CLEARANCE
  C. cause tokens        — CAUSE_DEMAND_SURGE ... CAUSE_UNKNOWN
  D. model-mismatch      — MODEL_MISSES_ONSET ... MODEL_RIGHT_AVERAGE_WRONG_SHAPE
  E. scenario-benefit    — BENEFIT_DELAY_REDUCTION ... BENEFIT_BOTTLENECK_SHIFT
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

STATE_TOKENS = [
    "CBI_FREE_FLOW", "CBI_PRE_BREAKDOWN", "CBI_CONGESTION_ONSET",
    "CBI_QUEUE_GROWTH", "CBI_MIN_SPEED", "CBI_QUEUE_DISSIPATION",
    "CBI_RECOVERY", "CBI_RESIDUAL_CONGESTION", "CBI_CAPACITY_DROP",
]
CAUSE_TOKENS = [
    "CAUSE_DEMAND_SURGE", "CAUSE_CAPACITY_DROP", "CAUSE_INCIDENT",
    "CAUSE_WEATHER", "CAUSE_WORK_ZONE", "CAUSE_LANE_DROP",
    "CAUSE_RAMP_MERGE", "CAUSE_SIGNAL_SPILLBACK",
    "CAUSE_MANAGED_LANE_RESTRICTION", "CAUSE_UNKNOWN",
]
MISMATCH_TOKENS = [
    "MODEL_MISSES_ONSET", "MODEL_MISSES_RECOVERY",
    "MODEL_UNDERSTATES_DURATION", "MODEL_OVERSTATES_DURATION",
    "MODEL_UNDERSTATES_SPEED_DROP", "MODEL_WRONG_BOTTLENECK_LOCATION",
    "MODEL_RIGHT_AVERAGE_WRONG_SHAPE", "MODEL_MATCHES_EPISODE",
]
BENEFIT_TOKENS = [
    # Names deliberately avoid monetization-flavored words the 2026-07-08
    # policy panel (FHWA / MPO / BCA personas) struck as overclaiming:
    # duration change is a per-vehicle diagnostic, NOT vehicle-hours;
    # stop-and-go exposure is a crash-risk CORRELATE, never a crash
    # reduction; duration stability is NOT the federal LOTTR/TTTR measure.
    "BENEFIT_DURATION_REDUCTION", "BENEFIT_DURATION_STABILITY_GAIN",
    "BENEFIT_RECOVERY_IMPROVEMENT", "BENEFIT_STOP_AND_GO_EXPOSURE_REDUCED",
    "BENEFIT_BOTTLENECK_SHIFT", "DISBENEFIT_DURATION_INCREASE",
]

MONETIZATION_GUARDRAILS = [
    "duration change is per-vehicle congested-minutes, NOT vehicle-hours; "
    "VHD needs counted volume x lanes x segment length (never synthesized volume)",
    "stop-and-go exposure is a crash-risk correlate; it must NOT be monetized "
    "as crash reduction without a CMF/SPF safety model and crash data",
    "duration stability is not LOTTR/TTTR/buffer index; it cannot feed a "
    "reliability value-of-time without full travel-time distributions",
    "duration, deficit area, and stability derive from the SAME speed-deficit "
    "signal — never sum their monetized values (double counting)",
    "before/after comparisons hold demand fixed; monetized savings must be "
    "net of induced-demand rebound",
    "severity is vehicle-speed based; a person-throughput view (occupancy-"
    "weighted) may rank a transit/priority alternative differently",
]


# ---------------------------------------------------------------------------
# A+B: compile observed episodes into state tokens
# ---------------------------------------------------------------------------
def compile_tokens(df_qc: pd.DataFrame,
                   episodes: pd.DataFrame,
                   corridor: str = "CORRIDOR",
                   ranking: pd.DataFrame | None = None,
                   v_f_mph: float = 65.0) -> list[dict]:
    """Walk the CBI state machine over every valid episode; emit token dicts.

    Every token carries: what happened, when, where, the evidence and its
    confidence, a cause diagnosis (honest CAUSE_UNKNOWN when unsupported),
    downstream uses, and a planner_message in plain English.
    """
    spd_col = ("speed_mph_clean" if "speed_mph_clean" in df_qc.columns
               else "speed_mph")
    cls_by = {}
    if ranking is not None and len(ranking):
        cls_by = (ranking.groupby("sensor_uid")["bottleneck_class"]
                  .agg(lambda s: s.mode().iloc[0]).to_dict())
    mp_by = (df_qc.groupby("sensor_uid")["road_order"].first().to_dict()
             if "road_order" in df_qc.columns else {})

    tokens = []
    valid = episodes[episodes.get("is_valid_for_mu", pd.Series(True, index=episodes.index))]
    for ep in valid.itertuples():
        g = df_qc[(df_qc["sensor_uid"] == ep.sensor_uid)
                  & (df_qc["datetime"].dt.date.astype(str) == str(ep.date))]
        g = g.sort_values("datetime").reset_index(drop=True)
        v = g[spd_col].to_numpy(float)
        ts = g["datetime"].to_numpy()
        v_c = float(getattr(ep, "v_c_mph", 50.0))

        t1_time = getattr(ep, "t0_time", pd.NaT)   # pipeline t0 == memo T1 onset
        t2_time = getattr(ep, "t2_time", pd.NaT)
        t3_time = getattr(ep, "t3_time", pd.NaT)
        if pd.isna(t1_time):
            continue
        i1 = int(np.searchsorted(ts, np.datetime64(t1_time)))
        i2 = int(np.searchsorted(ts, np.datetime64(t2_time))) if not pd.isna(t2_time) else i1
        i3 = int(np.searchsorted(ts, np.datetime64(t3_time))) if not pd.isna(t3_time) else i2

        # memo T0: pre-breakdown — walk back from onset while speed declines
        i0 = i1
        while i0 > 0 and i0 > i1 - 12 and np.isfinite(v[i0 - 1]) and v[i0 - 1] >= v[i0]:
            i0 -= 1
        t0_time = pd.Timestamp(ts[i0]) if i0 < i1 else pd.Timestamp(ts[i1])

        # memo T4: residual clearance — speed back within 90% of v_f
        i4 = i3
        thresh = 0.9 * v_f_mph
        while i4 < len(v) - 1 and np.isfinite(v[i4]) and v[i4] < thresh:
            i4 += 1
        t4_time = pd.Timestamp(ts[min(i4, len(ts) - 1)])

        # severity: speed-deficit area below v_c over the episode (mph*h)
        win = slice(i1, min(i3 + 1, len(v)))
        dt_h = 5.0 / 60.0
        deficit = float(np.nansum(np.clip(v_c - v[win], 0, None)) * dt_h)

        # evidence & confidence
        qc_rate = (float(g["qc_pass"].mean()) if "qc_pass" in g.columns else np.nan)
        synth = bool(g["flow_synthetic"].any()) if "flow_synthetic" in g.columns else False
        conf = ("high" if qc_rate >= 0.9 and not synth
                else "medium" if qc_rate >= 0.7 else "low")
        flags = []
        if synth:
            flags.append("volume_synthesized_not_counted")
        if qc_rate < 0.9:
            flags.append(f"qc_pass_rate_{qc_rate:.2f}")

        # cause diagnosis — honest: only claim what the evidence supports
        causes, regime = [], str(getattr(ep, "regime", ""))
        dow = pd.Timestamp(str(ep.date)).dayofweek
        if regime == "event":
            causes.append("CAUSE_INCIDENT")           # duration outlier day
        if dow >= 5:
            causes.append("CAUSE_DEMAND_SURGE")       # weekend pattern
        cls = cls_by.get(ep.sensor_uid, "")
        if cls in ("active_bottleneck", "spillback_source"):
            causes.append("CAUSE_CAPACITY_DROP")
        if not causes:
            causes.append("CAUSE_UNKNOWN")

        dur_min = float(getattr(ep, "P_min", np.nan))
        rec_min = (float((t3_time - t2_time).total_seconds() / 60)
                   if not (pd.isna(t3_time) or pd.isna(t2_time)) else np.nan)
        vmin = float(getattr(ep, "min_speed_mph", np.nan))

        tokens.append({
            "token_id": "CBI_CONGESTION_EPISODE",
            "facility": corridor,
            "sensor_uid": str(ep.sensor_uid),
            "milepost_or_order": mp_by.get(ep.sensor_uid),
            "date": str(ep.date),
            "period": str(ep.period),
            "day_regime": ("weekend_surge" if dow >= 5 else "weekday"),
            "bottleneck_class": cls or "unclassified",
            "states": {
                "T0_PRE_BREAKDOWN": str(t0_time),
                "T1_ONSET": str(t1_time),
                "T2_WORST_STATE": str(t2_time),
                "T3_RECOVERY": str(t3_time),
                "T4_RESIDUAL_CLEARANCE": str(t4_time),
            },
            "internal_markers": {"pipeline_t0_index": int(getattr(ep, "t0_index", -1)),
                                 "dialect": "memo T1_ONSET == pipeline t0"},
            "metrics": {
                "congestion_duration_min": dur_min,          # T3 - T1
                "recovery_duration_min": rec_min,            # T3 - T2
                "min_speed_mph": vmin,
                "speed_threshold_mph": v_c,
                "speed_deficit_area_mph_h": round(deficit, 1),
            },
            "evidence": {
                "source": "detector_speed_series",
                "support_level": conf,
                "qc_pass_rate": None if np.isnan(qc_rate) else round(qc_rate, 3),
                "missing_data_flags": flags,
            },
            "diagnosis": {"likely_cause": causes,
                          "attribution": ("heuristic_pattern — weekend/outlier/"
                                          "class rules; pending incident-TIM/"
                                          "RCRS feed corroboration"),
                          "demand_supply_status": ("supply" if "CAUSE_CAPACITY_DROP" in causes
                                                   else "demand" if "CAUSE_DEMAND_SURGE" in causes
                                                   else "uncertain")},
            "model_use": {"calibration_target": True,
                          "scenario_comparison_target": True},
            "planner_message": _planner_message(
                corridor, ep, t1_time, t2_time, dur_min, rec_min, vmin, cls, conf),
            "public_message": _public_message(ep, t1_time, dur_min, vmin),
        })
    return tokens


def _public_message(ep, t1, dur, vmin) -> str:
    """Public-meeting-safe variant: no engineering nouns, no unit-opaque
    metrics, no causal claims (MPO-planner review, 2026-07-08)."""
    hrs, mins = int(dur // 60), int(dur % 60)
    dur_txt = (f"about {hrs} hour{'s' if hrs != 1 else ''}"
               + (f" {mins} minutes" if mins else "")) if hrs else f"about {mins} minutes"
    return (f"On {ep.date}, traffic near this location slowed to roughly "
            f"{vmin:.0f} mph starting around {pd.Timestamp(t1).strftime('%I:%M %p').lstrip('0')} "
            f"and stayed congested for {dur_txt}. This measurement describes "
            "the problem; possible fixes are evaluated separately.")


def _planner_message(corridor, ep, t1, t2, dur, rec, vmin, cls, conf) -> str:
    where = f"sensor {str(ep.sensor_uid).split('::')[-1]}"
    role = {"active_bottleneck": "an active capacity-binding bottleneck",
            "spillback_source": "a queue source that floods upstream",
            "queued_passive": "inside a queue caused elsewhere (do not treat as the cause)",
            "incident_related": "an anomalous (incident-like) day, not a recurring pattern",
            }.get(cls, "a congestion episode")
    return (f"On {ep.date} ({ep.period}), {corridor} at {where} shows {role}: "
            f"congestion onset {pd.Timestamp(t1).strftime('%H:%M')}, worst point "
            f"{pd.Timestamp(t2).strftime('%H:%M') if not pd.isna(t2) else 'n/a'} "
            f"at {vmin:.0f} mph, lasting {dur:.0f} minutes with a "
            f"{rec:.0f}-minute recovery. Evidence confidence: {conf}. "
            "Use as a calibration and scenario-comparison target — this defines "
            "the observed problem; only a No-Build/Build comparison shows a fix.")


# ---------------------------------------------------------------------------
# D: observed vs simulated -> model-mismatch tokens
# ---------------------------------------------------------------------------
def compare_tokens(observed: list[dict], simulated: list[dict],
                   onset_tol_min: float = 15.0,
                   duration_tol_pct: float = 20.0,
                   speed_tol_mph: float = 7.0) -> list[dict]:
    """Match episodes by (sensor, date, period); emit mismatch tokens.

    The one that matters most: MODEL_RIGHT_AVERAGE_WRONG_SHAPE — average
    conditions agree while onset/recovery/shape do not.
    """
    def key(t): return (t["sensor_uid"], t["date"], t["period"])
    sim = {key(t): t for t in simulated}
    out = []
    for ob in observed:
        sm = sim.get(key(ob))
        row = {"sensor_uid": ob["sensor_uid"], "date": ob["date"],
               "period": ob["period"], "tokens": [], "errors": {}}
        if sm is None:
            row["tokens"] = ["MODEL_MISSES_ONSET"]
            row["errors"]["note"] = "no simulated episode at this sensor-period"
            out.append(row)
            continue
        e = row["errors"]
        e["onset_time_error_min"] = _dt_min(ob, sm, "T1_ONSET")
        e["recovery_time_error_min"] = _dt_min(ob, sm, "T3_RECOVERY")
        dur_o = ob["metrics"]["congestion_duration_min"]
        dur_s = sm["metrics"]["congestion_duration_min"]
        e["duration_error_pct"] = round(100 * (dur_s - dur_o) / max(dur_o, 1), 1)
        e["min_speed_error_mph"] = round(
            sm["metrics"]["min_speed_mph"] - ob["metrics"]["min_speed_mph"], 1)
        e["deficit_area_error_pct"] = round(100 * (
            sm["metrics"]["speed_deficit_area_mph_h"]
            - ob["metrics"]["speed_deficit_area_mph_h"])
            / max(ob["metrics"]["speed_deficit_area_mph_h"], 0.1), 1)

        toks = []
        if abs(e["onset_time_error_min"]) > onset_tol_min:
            toks.append("MODEL_MISSES_ONSET")
        if abs(e["recovery_time_error_min"]) > onset_tol_min:
            toks.append("MODEL_MISSES_RECOVERY")
        if e["duration_error_pct"] < -duration_tol_pct:
            toks.append("MODEL_UNDERSTATES_DURATION")
        if e["duration_error_pct"] > duration_tol_pct:
            toks.append("MODEL_OVERSTATES_DURATION")
        if e["min_speed_error_mph"] > speed_tol_mph:
            toks.append("MODEL_UNDERSTATES_SPEED_DROP")
        # the flagship check: averages fine, shape wrong
        avg_ok = (abs(e["duration_error_pct"]) <= duration_tol_pct
                  and abs(e["min_speed_error_mph"]) <= speed_tol_mph)
        shape_bad = (abs(e["onset_time_error_min"]) > onset_tol_min
                     or abs(e["recovery_time_error_min"]) > onset_tol_min)
        if avg_ok and shape_bad:
            toks.append("MODEL_RIGHT_AVERAGE_WRONG_SHAPE")
        row["tokens"] = toks or ["MODEL_MATCHES_EPISODE"]
        out.append(row)
    return out


def _dt_min(ob, sm, marker) -> float:
    try:
        return round((pd.Timestamp(sm["states"][marker])
                      - pd.Timestamp(ob["states"][marker])).total_seconds() / 60, 1)
    except Exception:
        return float("nan")


# ---------------------------------------------------------------------------
# E: before/after -> scenario-benefit tokens (planning language)
# ---------------------------------------------------------------------------
def benefit_tokens(before: list[dict], after: list[dict],
                   corridor: str = "CORRIDOR") -> dict:
    """Translate a No-Build/Build (or before/after) token comparison into
    planning-language benefit tokens. Never says 'the project is proven' —
    it names which observed dimensions improved."""
    def agg(tok_list):
        if not tok_list:
            return dict(dur=np.nan, rec=np.nan, deficit=np.nan, n=0,
                        dur_std=np.nan, top=None)
        dur = [t["metrics"]["congestion_duration_min"] for t in tok_list]
        rec = [t["metrics"]["recovery_duration_min"] for t in tok_list]
        dfc = [t["metrics"]["speed_deficit_area_mph_h"] for t in tok_list]
        worst = max(tok_list, key=lambda t: t["metrics"]["speed_deficit_area_mph_h"])
        return dict(dur=float(np.nanmedian(dur)), rec=float(np.nanmedian(rec)),
                    deficit=float(np.nanmedian(dfc)), n=len(tok_list),
                    dur_std=float(np.nanstd(dur)), top=worst["sensor_uid"])
    b, a = agg(before), agg(after)
    toks, lines = [], []

    def pct(x, y): return 100 * (y - x) / max(x, 1e-9)
    if a["dur"] < b["dur"] * 0.95:
        toks.append("BENEFIT_DURATION_REDUCTION")
        lines.append(f"median congested duration {b['dur']:.0f} -> {a['dur']:.0f} min "
                     f"({pct(b['dur'], a['dur']):+.0f}%) — a per-vehicle diagnostic, "
                     "NOT vehicle-hours of delay")
    if a["rec"] < b["rec"] * 0.95:
        toks.append("BENEFIT_RECOVERY_IMPROVEMENT")
        lines.append(f"median recovery {b['rec']:.0f} -> {a['rec']:.0f} min — "
                     "improved incident resilience")
    if a["deficit"] < b["deficit"] * 0.95:
        toks.append("BENEFIT_STOP_AND_GO_EXPOSURE_REDUCED")
        lines.append(f"median speed-deficit area {b['deficit']:.0f} -> "
                     f"{a['deficit']:.0f} mph-h — less stop-and-go exposure "
                     "(a crash-risk correlate, NOT a crash reduction)")
    if a["dur_std"] < b["dur_std"] * 0.9:
        toks.append("BENEFIT_DURATION_STABILITY_GAIN")
        lines.append(f"day-to-day duration spread {b['dur_std']:.0f} -> "
                     f"{a['dur_std']:.0f} min — a stability indicator "
                     "(not the federal LOTTR/TTTR reliability measure)")
    if a["top"] is not None and b["top"] is not None and a["top"] != b["top"]:
        toks.append("BENEFIT_BOTTLENECK_SHIFT")
        lines.append(f"worst location moved {b['top']} -> {a['top']} — the project "
                     "may relocate congestion; check the new location")
    if a["dur"] > b["dur"] * 1.05:
        toks.append("DISBENEFIT_DURATION_INCREASE")
        lines.append(f"median congestion duration INCREASED {b['dur']:.0f} -> "
                     f"{a['dur']:.0f} min")
    caveat = (" Caveats: comparison holds demand fixed (induced-demand rebound "
              "not represented); the duration/exposure/stability measures share "
              "one speed-deficit signal — do not sum monetized values; "
              f"based on {b['n']} vs {a['n']} episodes without significance "
              "testing — treat small differences as noise.")
    msg = ((f"{corridor}: the scenario does not only change average delay. "
            + " ".join(lines) + caveat) if lines else
           f"{corridor}: no material change detected between scenarios." + caveat)
    return {"tokens": toks, "before": b, "after": a,
            "planner_message": msg,
            "monetization_guardrails": MONETIZATION_GUARDRAILS}


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------
def write_tokens(tokens: list[dict], out_dir,
                 mismatches: list[dict] | None = None,
                 benefits: dict | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "cbi_tokens.jsonl", "w", encoding="utf8") as f:
        for t in tokens:
            f.write(json.dumps(t, default=str) + "\n")
    rows = [{
        "sensor_uid": t["sensor_uid"], "date": t["date"], "period": t["period"],
        "class": t["bottleneck_class"],
        **{k: t["states"][k] for k in t["states"]},
        **t["metrics"],
        "confidence": t["evidence"]["support_level"],
        "likely_cause": ";".join(t["diagnosis"]["likely_cause"]),
    } for t in tokens]
    pd.DataFrame(rows).to_csv(out / "cbi_event_table.csv", index=False)

    memo = ["# CBI calibration memo (auto-generated by the token compiler)", ""]
    memo.append(f"{len(tokens)} observed congestion-state tokens compiled. "
                "Each is a calibration target: reproduce its onset, worst point, "
                "duration, and recovery — not only the average travel time.")
    if mismatches:
        n_bad = sum(1 for m in mismatches if m["tokens"] != ["MODEL_MATCHES_EPISODE"])
        memo += ["", f"## Observed vs simulated: {n_bad}/{len(mismatches)} "
                 "episodes carry mismatch tokens", ""]
        for m in mismatches:
            if m["tokens"] != ["MODEL_MATCHES_EPISODE"]:
                memo.append(f"- {m['sensor_uid']} {m['date']} {m['period']}: "
                            f"{', '.join(m['tokens'])} — {m['errors']}")
    if benefits:
        memo += ["", "## Scenario benefit translation", "",
                 benefits["planner_message"], "",
                 f"tokens: {', '.join(benefits['tokens']) or '(none)'}"]
    memo += ["", "Language rule: these tokens define the observed operational "
             "problem and the calibration/benefit target. They do not prove a "
             "project; only the No-Build/Build comparison does."]
    (out / "cbi_calibration_memo.md").write_text("\n".join(memo), encoding="utf8")
    return out
