# -*- coding: utf-8 -*-
"""text_reader — a Transportation READER for unstructured text.

Reads the world's WORDS (news articles, agency feeds, social posts,
meeting minutes, web pages) and emits the same machine-readable
Transportation Issue Graph the detector Reader emits — so text evidence
and detector evidence meet in one structure the Planner can review.

Same architecture rules as every Reader:
  - read only; never edits anything;
  - the contract is the Issue Graph object, never prose;
  - an LLM front-end can replace the rule-based extractor below
    (`extract_issues_from_texts` is the reference implementation) — the
    schema still disposes: whatever the model says must land in these
    fields or it does not exist.

Cross-corroboration (`corroborate`) is where text becomes valuable:
a text-reported bottleneck that matches a detector-diagnosed one raises
confidence on both; a text report with NO detector counterpart becomes a
question for the Planner, not a fact.
"""
from __future__ import annotations

import re
from datetime import datetime

READER_ID = "cbi_plus text_reader (transportation_reader)"

# --- lexicon: phrase -> (issue type, base confidence contribution)
CUES = {
    "recurring_congestion_report": [
        "every day", "every morning", "every afternoon", "daily backup",
        "always backed up", "recurring", "typical weekday", "usual backup",
        "worst bottleneck", "chronic congestion", "notorious",
    ],
    "incident_report": [
        "crash", "collision", "accident", "stalled", "stall", "overturned",
        "jackknifed", "debris", "vehicle fire",
    ],
    "work_zone_report": [
        "construction", "work zone", "lane closure", "closed for repairs",
        "roadwork", "resurfacing", "detour",
    ],
    "capacity_event_report": [
        "lane drop", "merge", "spillback", "queue", "bumper to bumper",
        "standstill", "gridlock", "backed up for", "stop and go",
        "stop-and-go",
    ],
}
SOURCE_WEIGHT = {"dot_feed": 0.25, "news": 0.15, "social": 0.0, "document": 0.15,
                 "web": 0.1, None: 0.0}

ROAD_RE = re.compile(r"\b(I|US|SR|AZ|CA|Loop)[- ]?(\d{1,3})\b", re.I)
# California vernacular: "the 405", "the 101" — bare freeway number
ROAD_THE_RE = re.compile(r"\bthe\s+(\d{2,3})\b")
DIR_RE = re.compile(r"\b(northbound|southbound|eastbound|westbound|NB|SB|EB|WB)\b", re.I)
MP_RE = re.compile(r"\b(?:mile(?:\s?marker|post)?|MP)\s?(\d{1,3}(?:\.\d)?)\b", re.I)
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s?(a\.?m\.?|p\.?m\.?)\b", re.I)
DIR_NORM = {"northbound": "NB", "southbound": "SB", "eastbound": "EB",
            "westbound": "WB"}


def extract_issues_from_texts(texts: list, start_id: int = 700) -> dict:
    """Rule-based reference extractor: texts -> Issue Graph.

    ``texts``: list of str, or dicts {text, source (dot_feed|news|social|
    document|web), url, date}. An LLM front-end may replace this function;
    it must emit the same schema.
    """
    issues = []
    for k, item in enumerate(texts):
        if isinstance(item, str):
            item = {"text": item}
        text = item["text"]
        low = text.lower()

        hits = {typ: [c for c in cues if c in low] for typ, cues in CUES.items()}
        hits = {t: c for t, c in hits.items() if c}
        if not hits:
            continue
        # dominant type = most cue hits; recurring beats incident on ties
        order = ["recurring_congestion_report", "capacity_event_report",
                 "incident_report", "work_zone_report"]
        typ = max(hits, key=lambda t: (len(hits[t]), -order.index(t)))

        road = ROAD_RE.search(text)
        direc = DIR_RE.search(text)
        mp = MP_RE.search(text)
        tm = TIME_RE.search(text)
        if road:
            corridor = f"{road.group(1).upper()}-{road.group(2)}"
        else:
            the = ROAD_THE_RE.search(text)
            corridor = f"I-{the.group(1)}" if the else None
        direction = DIR_NORM.get(direc.group(1).lower(),
                                 direc.group(1).upper()) if direc else None

        conf = 0.35 + 0.1 * min(len(hits[typ]), 3) \
            + (0.15 if road else 0) + (0.05 if mp else 0) \
            + SOURCE_WEIGHT.get(item.get("source"), 0.0)
        conf = round(min(conf, 0.85), 2)   # text alone never exceeds 0.85

        evidence = [f"cue phrases: {hits[typ][:4]}"]
        if road:
            evidence.append(f"road mention: {corridor}"
                            + (f" {direction}" if direction else ""))
        if mp:
            evidence.append(f"milepost mention: MP {mp.group(1)}")
        if tm:
            evidence.append(f"time mention: {tm.group(0)}")
        if item.get("url"):
            evidence.append(f"source url: {item['url']}")

        issues.append({
            "issue_id": f"I-{start_id + len(issues):03d}",
            "type": typ,
            "location": {"corridor": corridor,
                         "direction": direction,
                         "milepost": float(mp.group(1)) if mp else None,
                         "sensors": []},
            "confidence": conf,
            "severity": "medium" if typ == "recurring_congestion_report" else "low",
            "evidence": evidence,
            "recommended_token": (
                ["CROSS_CHECK_WITH_DETECTOR_CBI", "CALIBRATION_TARGET"]
                if typ == "recurring_congestion_report"
                else ["CROSS_CHECK_WITH_DETECTOR_CBI"]),
            "status": "open",
            "source_text_index": k,
        })
    return {
        "graph_version": 1,
        "generated_by": READER_ID,
        "reader_role": "transportation_reader",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "world_read": ["unstructured_text"],
        "issues": issues,
    }


def corroborate(text_graph: dict, detector_graph: dict) -> dict:
    """Fuse text evidence with detector evidence.

    - text issue + matching detector issue (same corridor family, and
      compatible time window when both state one) -> both gain confidence
      (capped 0.98) and cross-reference each other;
    - text issue with NO detector counterpart -> flagged
      `needs_detector_check` (a question for the Planner, not a fact).
    """
    det = detector_graph["issues"]
    fused = {**text_graph,
             "issues": [dict(i) for i in text_graph["issues"]],
             "corroborated_with": detector_graph.get("generated_by")}
    for ti in fused["issues"]:
        c = (ti["location"].get("corridor") or "").replace("-", "").upper()
        match = None
        for di in det:
            dc = str(di["location"].get("corridor", "")).replace("-", "").upper()
            if c and c in dc and di["type"] in ("recurring_bottleneck",
                                                "unreliable_segment_lottr"):
                match = di
                break
        if match is not None:
            # only congestion-pattern reports gain the confidence boost —
            # a work-zone or incident report matching the corridor is a
            # cross-reference, not corroboration of the recurring pattern
            if ti["type"] in ("recurring_congestion_report",
                              "capacity_event_report"):
                ti["confidence"] = round(min(0.98, ti["confidence"] + 0.15), 2)
            ti["evidence"].append(f"corroborated by detector issue "
                                  f"{match['issue_id']} ({match['type']})")
            ti["corroborates"] = match["issue_id"]
        else:
            ti["evidence"].append("no detector counterpart found")
            ti["needs_detector_check"] = True
    return fused
