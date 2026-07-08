# Simulated review panel — 2026-07-08

Five persona agents (independent AI reviewers, each with a distinct academic
lens) reviewed the website, docs, notebooks, and API. This file records each
persona's top findings and the **disposition** — what was changed the same
day, and what remains open. Master traceability: [../ISSUE_REGISTER.md](../ISSUE_REGISTER.md) §8.

Personas: MIT CEE PhD (demand/DTA, Ben-Akiva lineage) · UC Berkeley
traffic-flow PhD (Daganzo/Cassidy school) · ASU CE junior (novice) ·
CS/ML PhD (API/reproducibility) · TU Delft senior researcher (scholarly
provenance, TR-C reviewer lens).

## The verdicts (before fixes)

- **MIT**: "the materials repeatedly borrow demand-side vocabulary for a
  tool that never observes demand — tighten every demand claim."
- **Berkeley**: "the ships-in-the-box simulator is too clean to teach the
  mechanisms it advertises — it never produces a measurable μ, hides the
  capacity drop, and violates conservation downstream."
- **ASU novice**: "I'd quit 8–10 minutes in, at the README install block —
  nobody tells me where to type pip." (also caught the NB01 prose-vs-table
  contradiction, independently of the CS reviewer)
- **CS/ML**: "marketing ships ahead of evidence: unpinned deps, no py.typed,
  swallowed exceptions, a self-test asserting one lucky seed."
- **Delft**: "fails every basic scholarly-provenance test in the first
  minute: no visible author, license, citation, version, or SI units."

## Findings → disposition

### Fixed same-day (SIM-P rows in the register)

| finding (persona) | fix |
|---|---|
| NB01 prose says SIM03 #1 but its own table shows SIM01 — seed-dependent ranking (ASU, CS) | simulator rewritten with real queue physics; ranking now SIM03 #1 across 10 seeds; `verify_installation` asserts 3 seeds |
| simulator: T2==T3 → no discharge window, μ never measurable; flat flow hides capacity drop; downstream conservation violated; hard 2.4 mi tail cutoff (Berkeley) | queue-balance rewrite: cumulative deficit queue, pre-breakdown flow ≈C then drop to μ=0.92C, downstream metered to bottleneck output, tail tapers naturally; NB02 now measures μ/C = 0.920 |
| NB02 treated `discharge_window`'s tuple as a dict (Berkeley) | fixed; μ computed from the window |
| `diagnose` swallowed exceptions into `{"error": str}` with shape-shifting return types (CS) | loud `warnings.warn` + stable None/frame types |
| unpinned dependencies (CS) | floors + caps in pyproject (`numpy>=1.24,<3`, `pandas>=2.0,<4`, …) |
| no `py.typed` (CS) | added to wheel |
| `verify_installation` asserted one lucky seed (CS) | multi-seed invariant (0/7/42), labeled a smoke test, removed from "evidence" framing |
| hidden temp-dir writes + stdout side effects in `diagnose` (CS) | in-memory by default; `run_ranking(out_dir=None)` pure mode |
| no author/license/citation/version on the site (Delft) | root LICENSE (MIT) + CITATION.cff; footer with lab name, version, license, citation, scope |
| "Tables 5–8 exact" vs benchmarks page "5/6/7" contradiction (Delft) | reconciled: 5/6/7 exact, Table 8 within tolerance |
| R²=0.977 branded a "law" with no scope (Delft) | labeled single-corridor, in-sample |
| gates presented as evidence without saying self-graded (Delft, MIT) | "internal reproduction gates, not external peer review" on the front page |
| jargon wall at README line 2; no where-do-I-type bridge (ASU) | plain-words opener + Glossary link on top + docs/SETUP_FOR_BEGINNERS.md linked from README/site/notebooks |
| notebook links look broken (raw JSON) to a local novice (ASU) | "open in Jupyter/VS Code" note next to notebook links |
| "demand accumulated" mislabels departures as demand (MIT, Berkeley — both independently) | GLOSSARY D entry rewritten as a demand *proxy* with the observability caveat; NB04 carries the note |
| "forward-only OD stance" gesture with no definition (MIT) | honest scope sentence in LINEAGE: single-location, OD-free, no feedback |
| AMS chain drawn without an equilibrium loop (MIT) | explicit one-pass-diagnostic scope statement in AMS_FRAMEWORK |
| "two numbers reproduce the day" vs four parameters (MIT) | phrasing corrected everywhere |
| capacity-drop range inconsistent 0.85–0.98 vs 0.85–0.95 (Berkeley) | standardized to 0.85–0.92 with Cassidy & Bertini 1999 cite in teaching text |
| faculty homepages cited instead of primary works (MIT, Delft) | DynaMIT, DYNASMART, Cassidy & Bertini, Vickrey added to references |
| "allies" framing implies endorsement (Delft) | reframed: "communities whose work we build on — no partnership implied" |
| R² as FD model scoreboard rewards the free-flow cloud (Berkeley) | caveat added in NB03; Newell NaN annotated as non-convergence |

### Open (register rows with OPEN status)

| finding | why open |
|---|---|
| single-detector T0/T2/T3 cannot by itself separate active/passive/moving-jam (Berkeley HIGH) | true and fundamental; stage-6 uses topology across sensors, but episode-level labeling language needs a docs pass (SIM-P1) |
| μ/C near-circularity (μ and C estimated from the same series) and drop defined vs FD-fit C not pre-breakdown peak (MIT/Berkeley) | needs a methodological change: report μ/C with C's CI, or define drop vs pre-queue peak (SIM-P2) |
| AI-arena claims: PINN registered but never run; single-seed MAEs; FLOW_TENSOR_MATH prose numbers without a backing table (CS) | arena rerun with seed sweep + honest PINN status is a compute task (SIM-P3) |
| flow_tensor price-of-rank measured partly against imputed cells (CS) | held-out-mask evaluation to implement (SIM-P4) |
| speed-only feeds with synthesized volume can produce zero valid discharge windows under the Δq guard (found re-testing) | needs a relaxed guard when flow_synthetic=True (SIM-P5) |
| z-score "event" days asserted as incidents from duration outliers alone (Berkeley) | rename/corroborate — language task (SIM-P6) |
| stage chatter uses print, not logging (CS) | logging migration (SIM-P7) |
| CI matrix (3.10–3.13), tests/ package in wheel (CS) | infra task (SIM-P8) |
| US-only scope / SI units parity (Delft) | scope stated in footer/README now; SI toggle is ENH-6b |
| full author list with affiliations/ORCIDs (Delft) | owner decision — ties to the named-table privacy split |

### What the personas praised (keep)

The "Your first day" ladder with time estimates (ASU: "the most welcoming
thing on the whole route"); the Glossary's D/C-in-hours pre-emption (ASU:
"where I finally felt smart"); honest "persistence beats the fancy methods"
arena reporting and explicit no-ODME non-goals (CS: "more scientifically
mature than most traffic-ML repos I review"); the Newell-cumulative-curve
plumbing and reproducible gates (all).
