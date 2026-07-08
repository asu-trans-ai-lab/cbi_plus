# -*- coding: utf-8 -*-
"""issue_graph — CBI as the Transportation READER.

Architecture rule (2026-07-08 memo): CBI reads the world and may NEVER
write to it. Its deliverable is not prose and not an edit — it is a
machine-readable **Issue Graph** (schemas/issue_graph.schema.json):
structured issue objects with type, involved network objects, confidence,
evidence, and *suggested* writer tokens. A Writer (Token2Net) acts only on
issues the Planner has explicitly approved. The Planner stays in the loop;
the AI never loops itself.

    World  ─Reader→  Issue Graph  ─Planner review→  approved issues
           ─Writer→  patch  ─validation→  simulation → report

Prose (`planner_message`, `public_message`) is demoted to a `rendering`
field: generated FROM the structure, never the contract. Writers must
ignore it.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

READER_ID = "cbi_plus transportation_reader"


def build_issue_graph(diagnose_out: dict,
                      corridor: str | None = None) -> dict:
    """Compile an api.diagnose() result into a Transportation Issue Graph.

    Issue sources (all read-only observations):
      - state tokens        -> recurring_bottleneck / incident_pattern_day
      - ranking classes     -> spillback_source / queued_passive context
      - fd_summary fit_ok   -> fd_fit_implausible
      - qc summary          -> data_quality
    """
    issues = []
    n = 0

    def iid():
        nonlocal n
        n += 1
        return f"I-{n:03d}"

    tokens = diagnose_out.get("tokens") or []
    ranking = diagnose_out.get("ranking")
    corridor = corridor or (tokens[0]["facility"] if tokens else "CORRIDOR")

    # --- recurring bottlenecks: aggregate episode tokens per sensor-period
    by_sp: dict = {}
    for t in tokens:
        by_sp.setdefault((t["sensor_uid"], t["period"]), []).append(t)
    for (sid, period), ts in sorted(by_sp.items()):
        cls = ts[0]["bottleneck_class"]
        incident_days = [t for t in ts if "CAUSE_INCIDENT" in t["diagnosis"]["likely_cause"]]
        recurring = [t for t in ts if t not in incident_days]
        conf_map = {"high": 0.85, "medium": 0.7, "low": 0.45}  # detector-only cap (Contract 4)
        if len(recurring) >= 2 and cls in ("active_bottleneck", "spillback_source"):
            dur = float(np.median([t["metrics"]["congestion_duration_min"] for t in recurring]))
            issues.append({
                "issue_id": iid(),
                "type": "recurring_bottleneck",
                "location": {"sensors": [sid], "corridor": corridor,
                             "time_window": period},
                "confidence": round(float(np.mean(
                    [conf_map[t["evidence"]["support_level"]] for t in recurring])), 2),
                "severity": "high" if dur >= 120 else "medium",
                "evidence": [f"{len(recurring)} recurring episodes",
                             f"median congestion_duration_min {dur:.0f}",
                             f"bottleneck_class {cls}",
                             f"median min_speed_mph "
                             f"{np.median([t['metrics']['min_speed_mph'] for t in recurring]):.0f}"],
                "recommended_token": ["CALIBRATION_TARGET", "SCENARIO_COMPARISON_TARGET"],
                "status": "open",
                "rendering": {"planner_message": recurring[0]["planner_message"],
                              "public_message": recurring[0]["public_message"]},
            })
        for t in incident_days:
            issues.append({
                "issue_id": iid(),
                "type": "incident_pattern_day",
                "location": {"sensors": [sid], "corridor": corridor,
                             "time_window": f"{t['date']} {period}"},
                "confidence": 0.6,   # heuristic duration-outlier attribution
                "severity": "low",
                "evidence": ["duration z-score outlier day (heuristic; pending "
                             "incident-TIM feed)",
                             f"congestion_duration_min {t['metrics']['congestion_duration_min']:.0f}"],
                "recommended_token": ["EXCLUDE_FROM_RECURRING_CALIBRATION"],
                "status": "open",
            })

    # --- implausible FD fits (physics gate failures)
    fs = diagnose_out.get("fd_summary")
    if fs is not None and "fit_ok" in fs.columns:
        for r in fs[~fs["fit_ok"]].itertuples():
            issues.append({
                "issue_id": iid(),
                "type": "fd_fit_implausible",
                "location": {"sensors": [str(r.sensor_uid)], "corridor": corridor},
                "confidence": 0.85,
                "severity": "medium",
                "evidence": [f"capacity_vphpl {r.capacity_vphpl}",
                             f"r_squared {r.r_squared}",
                             "outside physics band 1200-2600 vphpl / r2>0 / vf 40-90"],
                "recommended_token": ["REVIEW_DETECTOR_DATA", "EXCLUDE_FROM_FD_POOL"],
                "status": "open",
            })

    # --- data-quality
    qc = (diagnose_out.get("summary") or {}).get("qc") or {}
    rate = qc.get("qc_pass_rate")
    if isinstance(rate, (int, float)) and rate < 0.8:
        issues.append({
            "issue_id": iid(),
            "type": "data_quality",
            "location": {"corridor": corridor},
            "confidence": 0.9,
            "severity": "high",
            "evidence": [f"qc_pass_rate {rate}"],
            "recommended_token": ["REVIEW_DETECTOR_DATA"],
            "status": "open",
        })

    return {
        "graph_version": 1,
        "generated_by": READER_ID,
        "reader_role": "transportation_reader",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "world_read": ["detector_speed_series"]
        + (["detector_counts"] if fs is not None else []),
        "corridor": corridor,
        "issues": issues,
    }


def mismatch_issues(mismatches: list[dict], start_id: int = 900) -> list[dict]:
    """Model-mismatch comparisons as issue objects (calibration dialogue)."""
    out = []
    for i, m in enumerate(m for m in mismatches
                          if m["tokens"] != ["MODEL_MATCHES_EPISODE"]):
        out.append({
            "issue_id": f"I-{start_id + i:03d}",
            "type": "model_mismatch",
            "location": {"sensors": [m["sensor_uid"]],
                         "time_window": f"{m['date']} {m['period']}"},
            "confidence": 0.8,
            "severity": "medium",
            "evidence": [f"{k} {v}" for k, v in m["errors"].items()],
            "recommended_token": m["tokens"],
            "status": "open",
        })
    return out


def write_issue_graph(graph: dict, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, indent=2, default=str), encoding="utf8")
    return path


def planner_review(graph: dict, decisions: dict, reviewer: str) -> dict:
    """Apply Planner decisions {issue_id: 'approved'|'rejected'} to the graph.

    This is the ONLY function allowed to flip status to approved/rejected —
    and it demands an explicit reviewer name: the approval is a signed act,
    not a default. Writers must check status == 'approved'.
    """
    if not reviewer or not reviewer.strip():
        raise ValueError("planner_review requires a named reviewer — "
                         "approval is a signed act, never a default")
    g = json.loads(json.dumps(graph, default=str))     # deep copy
    now = datetime.now().isoformat(timespec="seconds")
    for iss in g["issues"]:
        d = decisions.get(iss["issue_id"])
        if d in ("approved", "rejected"):
            iss["status"] = d
            iss["review"] = {"reviewer": reviewer, "decision_time": now}
    return g


def approved_issues(graph: dict) -> list[dict]:
    """What a Writer is allowed to see: approved issues only, prose stripped.

    Enforces the Reader firewall (READER_PLANNER_WRITER.md rule 3): refuses
    any graph not emitted by a transportation_reader, and any 'approved'
    issue lacking a named reviewer. (Independent review, Jinxi Wu 2026-07-08,
    finding #1 — the doc promised this check but only the Writer-side repo
    enforced it; now both sides do.)
    """
    if graph.get("reader_role") != "transportation_reader":
        raise ValueError(
            "refusing issue graph: not emitted by a transportation_reader "
            "(a Writer must never act on unattributed observations)")
    out = []
    for iss in graph["issues"]:
        if iss.get("status") == "approved":
            if not (iss.get("review") or {}).get("reviewer"):
                raise ValueError(f"{iss.get('issue_id')}: approved without a "
                                 "named reviewer — refusing (approval is a "
                                 "signed act)")
            w = {k: v for k, v in iss.items() if k != "rendering"}
            out.append(w)
    return out
