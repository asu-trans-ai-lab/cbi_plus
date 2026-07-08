# RAG_EVIDENCE_COMPILER — RAG as a Transportation Evidence Compiler

**Design memo (2026-07-08):** do not make the Chrome connector the core
RAG path. Chrome / external GPT dialogue is an OPTIONAL expert-interview
source, never the backbone. **Chrome failure never blocks a RAG run.**

> RAG feeds the Transportation Issue Graph. It does not edit code, patch
> networks, or make final claims.
> **Text can suggest. Data must confirm. Planner must approve. Writer may
> only act after approval.**

## The pipeline

```
Source Registry -> Evidence Cards -> hybrid retrieval -> claim
classification -> detector corroboration -> Transportation Issue Graph
-> Planner review -> (optional) Writer action
```

Implementation: `cbi_pipeline/evidence.py` —
`api.register_source / make_evidence_card / compile_evidence /
write_source_registry`; live registry:
[knowledge/source_registry.json](knowledge/source_registry.json).

## The four-source stack (priority order)

| priority | source | examples | trust |
|---|---|---|---|
| A | internal project memory | ISSUE_REGISTER, FIXES logs, GLOSSARY, audits, release notes | project_internal |
| B | tool/runtime evidence — **overrides all text** | diagnose output, FD/QVDF/PM3/VHD results, benchmark gates | measurement |
| C | public authoritative web | FHWA, Caltrans, ADOT, RITIS/CATT, papers, agency project pages | official_policy / agency_report / peer_reviewed / news_context |
| D | external GPT / expert dialogue | Q&A, alternative framing, objections, terminology | expert_opinion — can SUGGEST issues, can never VALIDATE them |

## Contract 4 — confidence ceilings (enforced in code)

| evidence pattern | max confidence |
|---|---:|
| social text only | 0.40 |
| news text only | 0.55 |
| agency text only | 0.70 |
| peer-reviewed / official method | 0.80 |
| detector evidence only | 0.85 |
| text + detector corroboration | 0.90 |
| benchmark reproduction + detector | 0.95 |

Enforced in `evidence.CONFIDENCE_CAPS`, `text_reader.corroborate`
(<= 0.90), and `issue_graph.build_issue_graph` (detector-only <= 0.85).
Claims that REQUIRE detectors (bottleneck_location, capacity, reliability,
VHD) but lack them are stamped `needs_detector_check` — a Planner
question, never a fact.

## Claim types and their evidence requirements

See `evidence.CLAIM_REQUIREMENTS` — the table is executable, not prose:
bottleneck existence needs detector diagnosis + location consistency;
"an article says congestion is severe" needs only the article (and stays
`corridor_context`); VHD needs measured volume (`compute_vhd` refuses
synthesized by construction); PM3 needs speed + lengths + federal periods;
a code bug needs a reproducible trace; a teaching gap needs user-confusion
evidence. HCM facility-capacity claims have no gate yet (RAG-8, open).

## Chrome-failure fallback (the standard, exercised live 2026-07-08)

1. save the intended questions; 2. mark the dialogue source
`pending_transcript` in the registry; 3. answer first-pass from public web
+ internal docs; 4. create provisional issue objects; 5. flag
`needs_external_dialogue`; 6. later paste the transcript
([template](reviews/templates/expert_dialogue_transcript_template.md)) or
rerun the connector; 7. update confidence only after transcript review.
This is exactly what happened with the travel-demand-modeling GPT: the
run continued, Q1/Q2 were answered from literature, KNW-4 stays pending —
**a pending interview, not a failed RAG run.**
