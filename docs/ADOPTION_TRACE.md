# ADOPTION_TRACE — where each of Simon's positioning suggestions landed

Point-by-point traceability from the 2026-07-08 repositioning memo ("CBI/QVDF
is not a pile of Python scripts — it is a next-generation training platform")
to the repo. Three statuses: **ENFORCED** (code makes it impossible to skip),
**DOCUMENTED** (written contract, human-checked), **GAP** (accepted, not yet
built — listed with effort).

## The repositioning itself

| Suggestion | Where it landed | Status |
|---|---|---|
| "Not a data-processing script — a training & verification platform" | docs/MISSION.md (opening) | DOCUMENTED |
| The medical-school analogy | MISSION.md + image prompt #2 | DOCUMENTED |
| "Do we actually understand freeway congestion?" as the anchor question | MISSION.md headline | DOCUMENTED |
| "AI must be constrained, explained, verified by traffic-flow theory" | MISSION.md closing + THEORY_FOUNDATIONS.md final section | DOCUMENTED (its five concrete failure modes each map to an enforcing gate) |

## The seven principles

| # | Principle | Landed | Status |
|---|---|---|---|
| 1 | Input contract first | CONTRACTS.md §1–2; loaders emit TIMESERIES_COLUMNS; v4 adapter consumes shipped chain_fd | ENFORCED for units/order/lanes/is_observed; **GAP: facility type + merge/diverge annotation are documented but no loader requires them** (effort: schema column + loader warnings, ~half day) |
| 2 | Benchmarks before all-data | repro_gates (25/25 PASS); benchmarks/ in-repo; MISSION principle 2 | ENFORCED |
| 3 | Active vs passive bottleneck | stage6 classes (active_bottleneck / queued_passive / spillback_source / isolated_uncertain) in every ranking CSV | ENFORCED; **GAP: no explicit `incident` class** — event regime exists in stage 2 but is not fused into the stage-6 label (effort: join regime into classifier, ~1 h) |
| 4 | Per-day vs average vs period labeling | PERIOD_SLICE_BOUNDS; MDPM merge; `aggregation_level` column | ENFORCED in stage-6 CSVs; **GAP: stage-4/5b CSVs don't carry the column yet** (effort: add column, ~1 h) |
| 5 | Physics gates on everything | benchmark_gates: capacity band, μ/C band, v_t2<v_c, round-trip, **MAE ≤ 10 mph hard gate** | ENFORCED |
| 6 | CBI ranking is the deliverable | stage6 emits benchmark_bottleneck_ranking.csv + corridor summary; wired into every workflow run | ENFORCED |
| 7 | A new student can learn it | GLOSSARY, learning ladder in README, hello-world (paper reproduction), simulated-reader audits in docs/reviews/ | ENFORCED by process (audit repeats each doc change) |

## The six contracts (memo → CONTRACTS.md → code)

| Contract | Fields adopted | Enforced today | Gaps |
|---|---|---|---|
| 1 Corridor | all 8 fields | corridor_id/source/direction/order/milepost/lanes | facility_type, merge/diverge annotation (docs only) |
| 2 Observation | all 8 fields + the hard rule | timestamp/units/per-lane/is_observed (**imputed never calibrates** — enforced at adapters) | unified `detector_status` field (stage-1 has pass-rates, not a status enum) |
| 3 Period | table verbatim + 4 aggregation levels | slicing + MDPM in code | aggregation_level on all outputs (see principle 4 gap) |
| 4 Diagnosis | all 10 fields | T0/T2/T3/P/min_speed/bottleneck_type/confidence-class | `queue_length` + `wave_direction` are computed in dashboards/CBI-Lab, **not yet columns in episodes CSV** (effort: port spillExtent into stage 2, ~half day) |
| 5 Model | all 9 fields | FD type, C, μ (one implementation), μ/C band, v_c, D/C-hours, symbol map, FD R² gate, MAE hard gate | none — fully enforced |
| 6 Benchmark | file set + 3 required cases | all three cases reproduce; gates emit pass_fail_summary + comparison_report | file NAMES differ from the memo's exact set — **fixed today**: repro_gates now also emits `benchmark_expected_statistics.csv` + `benchmark_actual_statistics.csv` per the memo naming |

## The V/C / PHF teaching correction

| Suggestion | Landed |
|---|---|
| "Congestion is a dynamic process, not an hourly V/C" + corrections table | THEORY_FOUNDATIONS.md Part 1, table verbatim |
| The 8 diagnostic questions | THEORY_FOUNDATIONS.md Part 1 |
| LWR → Newell → Daganzo taught as the AI-constraining foundation, not "old theory" | THEORY_FOUNDATIONS.md Part 2, with the lineage chain, the textbook-vs-platform table, and the runnable CTM pointer |
| "V/C is not congestion. PHF is not dynamics. Low speed is not automatically a bottleneck." | verbatim, bolded, in THEORY_FOUNDATIONS.md |
| The five gated-away errors block | verbatim as the closing code block |
| FHWA / Newell / Daganzo / LWR references | references section |

## Honest remainder (the to-build list, priority order)

1. `aggregation_level` column on stage-4/5b outputs (~1 h)
2. `incident` fused into stage-6 bottleneck_type from the stage-2 event regime (~1 h)
3. queue_length + wave_direction as per-episode columns (~half day)
4. facility_type + merge/diverge annotation ingestion (~half day; v4 link.csv already carries is_ramp/is_merge/is_diverge)
5. unified detector_status enum in stage-1 output (~2 h)
