# ADD_VOCABULARY — the team playbook for extending the CBI+ vocabulary

*Written in response to the independent review (Jinxi Wu, ASU, 2026-07-08,
finding #4): "how would a team member add a new token or issue type?" — it
was possible but undocumented. This is the how-to.*

The CBI+ vocabulary is deliberately small and spread across a few files.
This page is the **map of where each kind of vocabulary lives** and a
**worked example** of adding one new cause token and one new issue type
end-to-end, with the honesty guardrails that keep new words trustworthy.

## Where the vocabulary lives (the map)

| vocabulary kind | file | what it is |
|---|---|---|
| **CBI state / cause / mismatch / benefit tokens** | `cbi_pipeline/cbi_tokens.py` — the module-top lists `STATE_TOKENS`, `CAUSE_TOKENS`, `MISMATCH_TOKENS`, `BENEFIT_TOKENS` | the planner-facing congestion vocabulary |
| **detector issue types** | `cbi_pipeline/issue_graph.py` — emitted as `"type": "..."` inside `build_issue_graph` | what CBI reports about a corridor |
| **RAG claim types + evidence requirements** | `cbi_pipeline/evidence.py` — `CLAIM_TYPES` list + `CLAIM_REQUIREMENTS` dict | what a retrieved claim asserts and what confirms it |
| **text-report cue lexicon** | `cbi_pipeline/text_reader.py` — the `CUES` dict | phrases that map raw text to a report type |
| **Token2Net writer tokens** | (Token2Net repo) `token2net/token_schema.json` — the `type` enum | the ONLY actions a Writer may take |
| **confidence caps** | `cbi_pipeline/evidence.py` — `CONFIDENCE_CAPS` | the honesty ceilings every new token inherits |
| **schema example strings** | `schemas/issue_graph.schema.json`, `schemas/dataset_meta.schema.json` — `description` fields | documentation, not enforcement |

**The golden rule:** a Reader token may *suggest*; only measurement
*confirms*; only a named Planner *approves*; only a Writer token *acts*.
A new word must declare which of those it is.

## Worked example A — add a new CAUSE token

Say you want `CAUSE_WEATHER` to fire when an external weather feed is
present. (It already exists as a placeholder; treat this as the pattern.)

1. **List it** — `cbi_pipeline/cbi_tokens.py`, add to `CAUSE_TOKENS`.
   (Already there; a brand-new one, e.g. `CAUSE_SPECIAL_EVENT`, goes here.)
2. **Emit it** — in `cbi_tokens.compile_tokens`, in the cause-diagnosis
   block, add the condition that appends it to `causes`. Keep it HONEST:
   assert it only when evidence supports it; otherwise `CAUSE_UNKNOWN`.
   ```python
   if event_calendar and date in event_calendar:   # external evidence
       causes.append("CAUSE_SPECIAL_EVENT")
   ```
3. **Document the evidence rule** — if the cause needs an external feed you
   don't have yet, stamp `diagnosis.attribution` so the token can't be read
   as confirmed (the existing `heuristic_pattern` note is the template).
4. **Test it** — add a case to the token battery (see the test stub below)
   asserting the token appears when its evidence is present and NOT when
   absent.

## Worked example B — add a new detector ISSUE TYPE

Say CBI should file a `weaving_section_instability` issue.

1. **Emit it** — in `issue_graph.build_issue_graph`, add a detector block
   that appends an issue dict with `"type": "weaving_section_instability"`,
   a `confidence` (respecting the detector-only cap 0.85), an `evidence`
   list of machine-checkable observations, a `recommended_token`, and
   `"status": "open"`.
2. **Give it an evidence requirement** — in `evidence.CLAIM_REQUIREMENTS`
   add `"weaving_section_instability": "detector diagnosis + geometry (merge/diverge tag)"`
   and add the type to `CLAIM_TYPES`. If it needs detectors to be trusted,
   add it to the `_NEEDS_DETECTOR` set so text-only mentions get
   `needs_detector_check`.
3. **Schema note** — add the type to the `description` example list in
   `schemas/issue_graph.schema.json` (documentation).
4. **Confidence cap** — nothing extra: `compile_evidence` applies the
   Contract-4 caps automatically. A new token can never be *more* confident
   than its evidence pattern allows.
5. **Writer side (only if it should drive an edit)** — add a matching token
   to `token2net/token_schema.json` and a rule in `writer.issues_to_tokens`.
   If it's diagnostic-only (most are), stop at step 4 — Readers never edit.

## The honesty checklist (every new word passes this)

- [ ] Is it a Reader word (suggests) or a Writer word (acts)? Never both.
- [ ] What evidence confirms it? Added to `CLAIM_REQUIREMENTS`.
- [ ] Does it need detectors? Added to `_NEEDS_DETECTOR`.
- [ ] Does its confidence respect `CONFIDENCE_CAPS`? (automatic if you
      route through `compile_evidence`).
- [ ] If it monetizes anything → it carries a `monetization_guardrails`
      caveat (see `cbi_tokens.MONETIZATION_GUARDRAILS`).
- [ ] Is there a test that it fires on its evidence and stays silent
      without it?

## The wiring test (drop-in)

Add to a `tests/test_vocabulary.py` so CI fails if a listed token is never
emitted or an emitted issue type isn't in `CLAIM_TYPES`:

```python
from cbi_pipeline import api, cbi_tokens, evidence
def test_every_claim_type_has_a_requirement():
    for ct in evidence.CLAIM_TYPES:
        assert ct in evidence.CLAIM_REQUIREMENTS, ct
def test_simulated_run_emits_valid_issue_types():
    out = api.diagnose(api.simulate_corridor(days=5, seed=0))
    g = api.build_issue_graph(out)
    known = set(evidence.CLAIM_TYPES) | {
        "recurring_bottleneck","incident_pattern_day",
        "fd_fit_implausible","data_quality","model_mismatch"}
    for iss in g["issues"]:
        assert iss["type"] in known, iss["type"]
```

## See also

- [CBI_TOKENS.md](CBI_TOKENS.md) — what the tokens *mean* (this page is how
  to *add* one).
- [RAG_EVIDENCE_COMPILER.md](RAG_EVIDENCE_COMPILER.md) — the four contracts
  and the confidence-cap table.
- [READER_PLANNER_WRITER.md](READER_PLANNER_WRITER.md) — the firewall a new
  word must respect.
