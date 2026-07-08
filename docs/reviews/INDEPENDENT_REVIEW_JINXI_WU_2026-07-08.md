# Independent Verification Record — Jinxi Wu (ASU), 2026-07-08

Formal first-time independent review of the cbi_plus codebase by a
data-and-mapping team member. Read-run-report; no files changed during the
review. Full findings triaged below with dispositions; register rows in
[../ISSUE_REGISTER.md](../ISSUE_REGISTER.md) §wave-9.

## Verdict (reviewer's words)

> A data-team newcomer can learn and *use* this in an afternoon — git-cold
> to a reproduced QVDF paper figure set and a full I-405 diagnosis in ~20
> minutes, README-only. Biggest strength: the onboarding-to-first-result
> path is real and honest. Biggest gap: parquet ingestion, a
> vocabulary-extension playbook, and the human-in-the-loop firewall were
> present in spirit but under-delivered — **the bones are strong; the gaps
> are documentation-and-wiring, not science.**

## What reproduced (verified independently)

| check | verdict | evidence |
|---|---|---|
| `api.verify_installation()` | PASS | 3 seeds, top=SIM03 as expected, CBI 2.07–2.20, `spillback_source`, ends PASS |
| QVDF paper **I-405** (`reproduce_casestudy2.py`) | PASS | C=1662, n=1.046, f_d=1.124, f_p=0.219, s=0.939; **self-consistency median 0.0000 h**; Figs 19–23 |
| QVDF paper **I-10** (`reproduce_qvdf_paper.py`) | PASS (runs) | Table 5/6/7 emitted; 1275 valid-days, 78% congested, avg 4.48 h |
| full pipeline on in-repo **I-405 PeMS** | PASS | 258,912 rows; FD R² 0.932–0.997 all `fit_ok`; 23 sensor-periods ranked |
| planner gate — no name | PASS | `ValueError: requires a named reviewer` |
| planner gate — with name | PASS | reviewer stamped at `issue["review"]["reviewer"]` |
| planner gate — **non-reader graph** | **FAIL → now FIXED** | tampered `reader_role` was accepted (finding #1) |

## Findings → disposition

### Fixed same-day (this release)

| # | finding | fix |
|---|---|---|
| 1 HIGH | `approved_issues` did not enforce the `reader_role` firewall the docs promised (accepted a tampered `reader_role`) | FIXED — `issue_graph.approved_issues` now refuses non-`transportation_reader` graphs and unsigned approvals; 3-test firewall battery PASS |
| 2/3 HIGH | parquet only via `tfb_adapter.py` (TFB-dir-bound, script-only); no `api` loader; `dataset_meta` enum had no parquet option | FIXED — `api.load_parquet(states_parquet, columns=…, speed_units=…, flow_scope=…)` mirrors `load_ieee_v4`; `dataset_meta` enum gains `parquet` + `load_dataset` dispatch; parquet→diagnose verified end-to-end |
| 4 HIGH | no "how to add a token / issue type" doc | FIXED — [ADD_VOCABULARY.md](../ADD_VOCABULARY.md): the vocabulary map, two worked examples, the honesty checklist, a drop-in wiring test |
| 5 MED | PINN reported SKIPPED "if torch importable" but is SKIPPED regardless (never coupled) | FIXED — `ai_arena.py` docstring + status string corrected to "coupling pending, regardless of torch" |
| 7 MED | I-405 study folder `qvdf_paper_casestudy2` doesn't say "I-405" | FIXED — README hello-world now names both (Case Study 1 = I-10, Case Study 2 = I-405) + onboarding playbook |
| 8 MED | cwd/PYTHONPATH friction for own scripts | FIXED — playbook step 0: `pip install -e .` |
| 9 MED | parquet round-trip drops `df.attrs` provenance silently | FIXED — CONTRACTS.md Contract-7 caveat + playbook note (rely on the columns, not `attrs`) |

### Documented playbooks created (the "playbook in making")

- [ADD_VOCABULARY.md](../ADD_VOCABULARY.md) — extend tokens / issue types / claim types.
- [PLAYBOOK_ONBOARD_CORRIDOR_AND_DATASET.md](../PLAYBOOK_ONBOARD_CORRIDOR_AND_DATASET.md) —
  loader decision tree (incl. parquet), the I-405 known-good anchor, the
  sidecar-first habit, expected-FAIL gates.

### Open (registered, not blocking)

| # | finding | register |
|---|---|---|
| 6 MED | engines are CLI-only; no `api.run_ai_arena` wrapper | JW-6 OPEN |
| 10 LOW | standardize an "expected gate outcomes" block in every benchmark README | JW-10 OPEN |
| 11 LOW | `verify_installation` prints a benign "FD fits fail" warning that reads scary | JW-11 — annotated in this release; full downgrade OPEN |
| 12 LOW | T0–T4 dialect double-mapping is a cross-referencing trip hazard | JW-12 OPEN (banner in CSV headers) |
| 13 LOW | reviewer stamp path `issue["review"]["reviewer"]` under-documented | FIXED in READER_PLANNER_WRITER example |
| 14 LOW | `discover` recognizes parquet but `load_dataset` couldn't load it (now can) | RESOLVED by finding #2/#3 |

## Bottom line

The independent review confirms the science reproduces exactly (I-405 QVDF
self-consistency 0.0000 h) and found **one real correctness bug** (the
firewall gap) plus three documentation/wiring gaps — all fixed or
documented in the same release. This record is the formal independent
verification requested.
