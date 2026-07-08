# READER / PLANNER / WRITER — the three-layer architecture

**Design memo (2026-07-08).** CBI and Token2Net must never be mixed into
one system, or the AI "improvises" and the system drifts out of control.
They are two different compilers with a human gate between them:

```
Layer 1   TRANSPORTATION READER   (CBI, network readers)
          reads the world; may NEVER write
─────────────────────────────────────────────────────────
Layer 2   TRANSPORTATION PLANNER  (human + AI)
          reviews evidence; approves or rejects
─────────────────────────────────────────────────────────
Layer 3   TRANSPORTATION WRITER   (Token2Net)
          writes patches; may NEVER read the world directly
```

## The two compilers

| | Reader (CBI) | Writer (Token2Net) |
|---|---|---|
| compiles | World → Observation → **Evidence** | **Evidence** → Action → Network Patch |
| reads | GMNS, geometry, probe, trajectory, OD, counts, signals, OSM, imagery, simulation results | approved issues ONLY |
| writes | nothing — it reports | GMNS patches through tokenized atomic edits |
| output | **Issue Graph** (machine objects) | patch plan + audit log + validation |
| may say "fix it" | no — it may *suggest* tokens | only after Planner approval |

## The contract: the Transportation Issue Graph

The ONLY channel between layers is a structured Issue Graph
([schemas/issue_graph.schema.json](../schemas/issue_graph.schema.json)) —
never free natural language:

```json
{
  "issue_id": "I-101",
  "type": "missing_turn",
  "location": {"nodes": [102]},
  "confidence": 0.97,
  "evidence": ["movement missing", "path disconnected"],
  "recommended_token": ["ADD_TURNING_MOVEMENT"],
  "status": "open"
}
```

Rules the code enforces:

1. **Readers emit objects, not prose.** Human-facing sentences
   (`planner_message`, `public_message`) live in an optional `rendering`
   field, generated FROM the structure — Writers strip and ignore it.
2. **Approval is a signed act.** `planner_review` refuses an empty
   reviewer name; a Writer refuses any "approved" issue without a named
   reviewer. The Planner stays in the loop — the AI never loops itself.
3. **Writers refuse unattributed graphs.** `approved_issues` rejects any
   graph whose `reader_role != "transportation_reader"`.
4. **Status lifecycle**: `open → approved|rejected → patched → validated`.
   Only the Planner sets approved/rejected; only the Writer sets patched;
   only validation sets validated.

## The workflow (Planner always in the loop)

```
Planner → CBI Reader → Issue List → Planner Review → Token Generator
        → Patch Plan → GMNS Editor → Validation → Simulation → Report
```

## Implementations

**Reader side (this repo)** — `cbi_pipeline/issue_graph.py`:
`api.build_issue_graph(diagnose_out)` compiles diagnostics into issues
(recurring_bottleneck, incident_pattern_day, fd_fit_implausible,
data_quality); `api.mismatch_issues(...)` adds model-mismatch issues;
`api.planner_review / api.approved_issues` implement the gate.

**Writer side (GMNS-Token2Net repo)** — `token2net/network_reader.py`
(topology Reader: missing_ramp, missing_turn, disconnected_node),
`token2net/writer.py` (gate + issues→tokens→patch), verified by
`demo_reader_writer.py`: a sabotaged diamond interchange (one ramp
removed, no movements) → Reader emits 3 issues (missing_ramp conf 0.96,
missing_turn conf 0.97 ×2) → named-planner approval → Writer patch →
full acceptance table PASS → firewall tests confirm the Writer refuses
non-Reader graphs and does nothing without approval.

## Why this matters

Read and write are fully decoupled: CBI stays objective (observe and
diagnose only), Token2Net stays controlled (execute approved changes
only), and everything that crosses the boundary is auditable structure.
The same pattern extends to OD calibration, signal optimization, and
demand modeling — each gets a Reader that files issues and a Writer that
patches only what the Planner signs.
