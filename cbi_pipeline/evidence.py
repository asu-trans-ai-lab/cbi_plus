# -*- coding: utf-8 -*-
"""evidence — the RAG Evidence Compiler (owner memo, 2026-07-08).

    Use RAG as a Transportation Evidence Compiler, not as a browser
    assistant. Text can suggest. Data must confirm. Planner must approve.
    Writer may only act after approval.

Pipeline: Source Registry -> Evidence Cards -> claim classification ->
detector corroboration -> Transportation Issue Graph -> Planner review.
Chrome / external GPT dialogue is an OPTIONAL expert-interview source
(trust 'expert_opinion'; can_create_issue, can_validate_issue = False) —
its failure never blocks a RAG run.

Four contracts:
  1. Source Registry — every source declares id, type, trust level,
     coverage, limitations.
  2. Evidence Card — every retrieved chunk becomes a typed card with a
     confidence PRIOR and a corroboration requirement.
  3. Claim types — different claims need different evidence (a bottleneck
     needs detectors; "an article says congestion is severe" needs only
     the article; VHD needs measured volume).
  4. Corroboration rule + confidence caps — hard ceilings by evidence
     pattern; nothing text-only ever outranks measurement.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

TRUST_LEVELS = [
    "measurement", "official_policy", "peer_reviewed", "project_internal",
    "agency_report", "news_context", "social_context", "expert_opinion",
    "llm_suggestion",
]

CLAIM_TYPES = [
    "corridor_context", "bottleneck_location", "incident_report",
    "work_zone_report", "capacity_claim", "reliability_claim", "VHD_claim",
    "HCM_facility_claim", "teaching_misunderstanding", "software_bug",
    "documentation_gap",
]

# Contract 4 — hard confidence ceilings by evidence pattern
CONFIDENCE_CAPS = {
    "social_text_only": 0.40,
    "news_text_only": 0.55,
    "agency_text_only": 0.70,
    "peer_reviewed_only": 0.80,
    "detector_only": 0.85,
    "text_plus_detector": 0.90,
    "benchmark_plus_detector": 0.95,
}
_TRUST_TEXT_CAP = {
    "social_context": CONFIDENCE_CAPS["social_text_only"],
    "news_context": CONFIDENCE_CAPS["news_text_only"],
    "agency_report": CONFIDENCE_CAPS["agency_text_only"],
    "official_policy": CONFIDENCE_CAPS["agency_text_only"],
    "peer_reviewed": CONFIDENCE_CAPS["peer_reviewed_only"],
    "project_internal": CONFIDENCE_CAPS["agency_text_only"],
    "expert_opinion": CONFIDENCE_CAPS["social_text_only"],
    "llm_suggestion": CONFIDENCE_CAPS["social_text_only"],
    "measurement": CONFIDENCE_CAPS["detector_only"],
}

# Contract 3 — what each claim type REQUIRES before it can firm up
CLAIM_REQUIREMENTS = {
    "bottleneck_location": "detector diagnosis + location consistency",
    "corridor_context": "web/agency source acceptable (context only)",
    "incident_report": "incident feed or detector event corroboration",
    "work_zone_report": "agency source acceptable; detector check for impact",
    "capacity_claim": "FD fit passing physics gates",
    "reliability_claim": "speed series + segment length + federal periods (PM3 layer)",
    "VHD_claim": "MEASURED volume (compute_vhd refuses synthesized)",
    "HCM_facility_claim": "facility type + lane group + capacity basis (gate OPEN: RAG-8)",
    "software_bug": "reproducible command or trace",
    "teaching_misunderstanding": "simulated-student / user confusion evidence",
    "documentation_gap": "specific doc location + what a reader could not do",
}
_NEEDS_DETECTOR = {"bottleneck_location", "incident_report", "capacity_claim",
                   "reliability_claim", "VHD_claim"}


# ---------------------------------------------------------------------------
# Contract 1 — Source Registry
# ---------------------------------------------------------------------------
def register_source(source_id: str, source_type: str, trust_level: str,
                    source_url_or_path: str = "", owner: str = "",
                    coverage_period: str = "", corridor: str = "",
                    can_support_claim_type: list | None = None,
                    limitations: str = "", status: str = "active") -> dict:
    if trust_level not in TRUST_LEVELS:
        raise ValueError(f"trust_level {trust_level!r} not in {TRUST_LEVELS}")
    return {
        "source_id": source_id,
        "source_type": source_type,
        "source_url_or_path": source_url_or_path,
        "retrieval_date": datetime.now().strftime("%Y-%m-%d"),
        "owner": owner,
        "trust_level": trust_level,
        "coverage_period": coverage_period,
        "corridor": corridor,
        "can_support_claim_type": can_support_claim_type or [],
        "limitations": limitations,
        "status": status,
        # expert dialogue / LLM sources may SUGGEST issues, never validate
        "can_create_issue": True,
        "can_validate_issue": trust_level == "measurement",
    }


# ---------------------------------------------------------------------------
# Contract 2 — Evidence Card
# ---------------------------------------------------------------------------
def make_evidence_card(source: dict, claim_text: str, claim_type: str,
                       corridor: str | None = None,
                       direction: str | None = None,
                       time_period: str | None = None,
                       ev_id: str | None = None) -> dict:
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f"claim_type {claim_type!r} not in {CLAIM_TYPES}")
    cap = _TRUST_TEXT_CAP[source["trust_level"]]
    return {
        "evidence_id": ev_id or f"EV-{abs(hash((source['source_id'], claim_text))) % 10_000:04d}",
        "source_id": source["source_id"],
        "source_type": source["source_type"],
        "trust_level": source["trust_level"],
        "claim_text": claim_text,
        "claim_type": claim_type,
        "corridor": corridor,
        "direction": direction,
        "time_period": time_period,
        "confidence_prior": round(min(0.9 * cap + 0.05, cap), 2),
        "confidence_cap": cap,
        "requires_detector_corroboration": claim_type in _NEEDS_DETECTOR,
        "requirement": CLAIM_REQUIREMENTS[claim_type],
    }


# ---------------------------------------------------------------------------
# The compiler: cards (+ detector graph) -> Issue Graph
# ---------------------------------------------------------------------------
def compile_evidence(cards: list[dict],
                     detector_graph: dict | None = None,
                     benchmark_pass: bool = False,
                     start_id: int = 800) -> dict:
    """Evidence cards -> Issue Graph with structured evidence arrays.

    Confidence per Contract 4: text priors are capped by trust level;
    detector corroboration lifts to <= 0.90 (<= 0.95 when the corridor also
    passes benchmark reproduction); claims that REQUIRE detectors but lack
    them are stamped needs_detector_check and stay at their text cap.
    """
    det_issues = (detector_graph or {}).get("issues", [])

    def det_match(corridor):
        c = (corridor or "").replace("-", "").upper()
        if not c:
            return None
        for di in det_issues:
            dc = str(di["location"].get("corridor", "")).replace("-", "").upper()
            if c and (c in dc or dc in c) and di["type"] in (
                    "recurring_bottleneck", "unreliable_segment_lottr"):
                return di
        return None

    # group cards by (corridor, claim_type)
    groups: dict = {}
    for c in cards:
        groups.setdefault(((c.get("corridor") or "GLOBAL"), c["claim_type"]), []).append(c)

    issues = []
    for n, ((corridor, claim_type), grp) in enumerate(sorted(groups.items())):
        ev = [{"source_type": c["source_type"], "trust_level": c["trust_level"],
               "claim": c["claim_text"], "evidence_id": c["evidence_id"]}
              for c in grp]
        text_conf = max(c["confidence_prior"] for c in grp)
        text_cap = max(c["confidence_cap"] for c in grp)
        needs_det = any(c["requires_detector_corroboration"] for c in grp)
        match = det_match(corridor) if corridor != "GLOBAL" else None

        if match is not None:
            cap = (CONFIDENCE_CAPS["benchmark_plus_detector"] if benchmark_pass
                   else CONFIDENCE_CAPS["text_plus_detector"])
            conf = round(min(cap, max(text_conf, match.get("confidence", 0)) + 0.1), 2)
            ev.append({"source_type": "detector_diagnosis",
                       "trust_level": "measurement",
                       "claim": f"corroborated by detector issue {match['issue_id']} "
                                f"({match['type']})",
                       "evidence_id": match["issue_id"]})
            flag = {}
        else:
            conf = round(min(text_conf, text_cap), 2)
            flag = ({"needs_detector_check": True} if needs_det else {})

        issues.append({
            "issue_id": f"RAG-{start_id + n:03d}",
            "type": claim_type,
            "location": {"corridor": None if corridor == "GLOBAL" else corridor,
                         "sensors": []},
            "confidence": conf,
            "severity": "medium" if match is not None else "low",
            "evidence": ev,
            "recommended_token": (["COMPARE_WITH_BENCHMARK",
                                   "GENERATE_CORRIDOR_DASHBOARD"]
                                  if match is not None
                                  else ["CROSS_CHECK_WITH_DETECTOR_CBI"]),
            "status": "needs_planner_review" if match is not None else "open",
            "claim_requirement": CLAIM_REQUIREMENTS[claim_type],
            **flag,
        })

    return {
        "graph_version": 1,
        "generated_by": "cbi_plus evidence_compiler (transportation_reader)",
        "reader_role": "transportation_reader",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "world_read": sorted({c["source_type"] for c in cards})
        + (["detector_diagnosis"] if det_issues else []),
        "issues": issues,
    }


def write_source_registry(sources: list[dict], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"registry_version": 1,
                                "sources": sources}, indent=2), encoding="utf8")
    return path
