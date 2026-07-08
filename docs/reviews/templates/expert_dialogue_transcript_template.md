# Expert dialogue transcript — [source_name]

source_id: SRC-...            (must exist in docs/knowledge/source_registry.json)
source_type: external_expert_dialogue
trust_level: expert_opinion   (can_create_issue: yes · can_validate_issue: NO)
status: captured              (pending_transcript -> captured -> reviewed)
interviewer: [name]
date: YYYY-MM-DD
channel: [chrome session / manual paste / in person]

## Turns

### Q1
> [question verbatim]

**A1 (verbatim):**
[answer]

**Evidence cards derived** (each claim -> one card via api.make_evidence_card):
- claim_type: ... | claim_text: "..." | corridor: ...

### Q2 ...

## Review
reviewer: [named planner]
issues created (RAG-xxx ids): ...
claims REJECTED as unsupported: ...
note: expert dialogue suggests; detectors confirm; planner approves.
