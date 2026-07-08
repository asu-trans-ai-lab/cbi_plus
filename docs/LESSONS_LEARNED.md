# Lessons learned — the CBI+ consolidation (2026-07-07/08)

What one integration pass over four public repos, two internal handoffs, three
bundle mirrors, one paper, and seven corridors taught us. Written for the next
person (or model) who touches this code.

## 1. Reproduction is the deliverable, not the code

Every gap the external review found — no data, no outputs, no ranking artifact
— reduces to one rule: **a result you cannot regenerate does not exist.** The
repo now enforces it mechanically: every benchmark folder is self-contained
(data + script + keyed reference values), and `python -m cbi_pipeline.repro_gates`
re-verifies all of them in one command. When an integration changes a number,
the gate fails loudly instead of the result drifting silently.

## 2. Calibration recipes survive only in artifacts

We could NOT reproduce the paper's Case-Study-2 coefficients from the method
text (binned means? Solver objective? which error?). The workbook
(`02-I405_Summary_4month.xlsx`) was the only ground truth — its cells encode
the exact objective. Corollary: ship the workbook/script, or the numbers die
with the author. (Case 1 reproduced exactly *because* the repo carried the
calibration script.)

## 3. Physical plausibility catches what R² hides

The ten pipeline fixes were invisible to goodness-of-fit and obvious to
physics: μ=306 vphpl (period-offset bug), capacity 9,443 vphpl (imputed
stations with R²=0.999 FD fits), D/C never exceeding 1 (units). Bands beat
metrics: μ/C ∈ 0.85–0.98, capacity 1,500–2,300, v_t2 < v_c. The benchmark
gates encode these permanently.

## 4. One physical quantity, one implementation

The worst review finding (stage-2b's μ uncorrelated with stage-4's, r=-0.01)
was a copy-pasted second implementation of the same quantity. Rule: physics
quantities get exactly one function; everything else calls it.

## 5. Indices must carry their frame

Three separate bugs (stage 4, stage 5, stage 2b) were the same bug: a
period-relative index applied to a day-relative frame. Any index stored in a
table needs its frame stated next to it (`PERIOD_SLICE_BOUNDS` +
`period_hour_mask` now make the frame explicit).

## 6. Window design is a modeling decision

The paper used single windows (7:00–21:00, 11:00–20:00); our AM/MD/PM split
truncated 84% of midday queues until the MD→PM merge. The PAQ repo's fixed
window [13:10–19:44] starts mid-queue, violating Q(t0)=0. Before any run, ask:
does the analysis window contain the whole queue?

## 7. Shape families are corridor-dependent — test, don't assume

Across the PAQ repo's own 22 days: trapezoid (R²=0.603) > quadratic (0.549)
≫ quartic (−0.26) ≫ cubic (−2.2). Long oversaturated queues are flat-topped;
single-peak polynomials fit only mild days. The same lesson appeared on
I-210E (quartic vs quadratic verdict flips per episode). The dashboards now
fit the family and report the verdict per queue object.

## 8. Priors are not measurements

Three incarnations of one mistake: OSM lane tags (lanes=2 on a 5,100 veh/h
section), TrafficFlowBench neighbor-imputation ingested as observations,
inverse-S3 synthesized volumes hitting their own prior's capacity ceiling.
Every map attribute, imputation, and synthesized quantity now carries a flag
(`gmns_lanes` vs effective lanes, `is_observed` filter, `flow_synthetic`).

## 9. Same corridor name ≠ same benchmark

I-405 exists here in three vintages (paper 4-month workbook, PeMS Mar-2018,
TFB 2025-26) with different detectors, extents and years. The dataset registry
(DATASETS.md), per-folder manifests, and vintage notes on every reproduction
page pin which is which. When a reviewer says "reproduce I-405," the first
question is *which I-405*.

## 10. Legacy repos are validation anchors, not code to merge

All four old repos' algorithms are superseded (Huber+bootstrap FD, hardened
scan, round-trip-verified QVDF, shrinkage aggregation, freq×dur×sev ranking) —
but their DATA and their published numbers are irreplaceable. The right
integration was: archive the code, vendor the datasets completely, reproduce
the published figures on their own data, key the numbers into gates, and write
the ancestry down (STAGE_CHAIN.md). Their bugs are preserved and documented
(Jayakrishnan bounds mismatch), not silently fixed — a reproduction that
"fixes" the original is no longer a reproduction.

## 11. Agreement, not exactness, across tool generations

Legacy CBI-main and modern cbi_plus scan the same Arizona feed with different
QC and persistence rules — per-link P correlates but does not match exactly.
Compare tool generations with correlation + MAE and a written explanation of
the rule differences; demanding exactness across generations would freeze
every improvement.

## 12. The workflow that made this fast

Dev/external split with a content-shape privacy validator between (the safe
path is the only path); a status dashboard that maps requirements to evidence
links (nothing gets lost); background pipeline runs while building the next
artifact; and an independent review agent on the outputs — it found five real
defects the builder missed. Build → audit → gate → page, for every result.
