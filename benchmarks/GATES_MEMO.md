# CPI/CBI/QVDF Benchmark Gates for I-10, I-405, and I-395/NVTA

Date: 2026-07-08
Purpose: strengthen the CPI/CBI/QVDF tool acceptance package so the tool is judged by reproducible corridor benchmarks, not by code existence alone.

## 0. Acceptance principle

The tool is not accepted unless it can reproduce prior benchmark cases with documented tolerances. A clean package must include:

- `data_manifest.csv`
- `run_manifest.json`
- `benchmark_reference_manifest.csv`
- `benchmark_comparison_report.csv`
- `quality_gates.json`
- `pass_fail_summary.csv`
- `open_issues.md`
- required plots for each corridor, direction, period, and benchmark case

The package must distinguish:

- per calendar day outputs,
- average weekday outputs,
- corridor-period aggregate outputs,
- paper/previous-run benchmark reference outputs.

Average weekday is a benchmark view, not a replacement for per-day analysis.

---

## 1. Required benchmark cases

| Case | Required role | Minimum required output |
|---|---|---|
| I-10 QVDF paper corridor | Paper-reproduction benchmark | Reproduce paper tables/figures/statistics within tolerance; especially speed profile, congestion duration, queue profile, and QVDF parameters. |
| I-405 California/PeMS | Internal PeMS calibration benchmark | Detector-by-detector and corridor-period reproduction; speed/flow/density/QVDF/queue profile outputs. |
| I-395 NVTA | Planning-model / INRIX-TMC benchmark | Corridor-level CBI/QVDF measures, bottleneck ranking, SOV/HOV and NB/SB consistency, observed-vs-QVDF speed profile. |

---

## 2. Evidence gates

| Gate | Rule | Status if missing |
|---|---|---|
| Dataset manifest | Each case has case name, source, date range, corridor, direction, sensor/TMC count, time resolution, observed fraction, units, lane source. | FAIL |
| Reference manifest | Each benchmark statistic is traceable to a paper table/figure, previous run file, or reviewed email/report. | FAIL |
| One-command reproduction | `python run_all_benchmarks.py --case <case> --out outputs/<case>` runs without manual edits. | FAIL |
| Output folder contract | Required stage folders and benchmark reports exist for every case. | FAIL |
| Environment reproducibility | Git hash, package version, Python version, dependency lock, run time, and machine info recorded. | FAIL |
| No private hard-coded paths | No `C:\...`, local user folder, or absolute private dataset path required. | FAIL |

---

## 3. PeMS data-quality gates

| Gate | Recommended threshold | Notes |
|---|---:|---|
| Observed-data fraction | >= 0.80 preferred; 0.60 minimum with REVIEW | Do not count imputed cells as observations. |
| Imputation mask respected | 100% required | Cells with `is_observed=False` must be blanked or separately flagged. |
| Speed range | 0–90 mph normal; >90 mph flagged | Use mph after unit conversion. |
| Flow range | 0–2,400 vphpl normal; >2,400 REVIEW/FAIL unless documented | Per-lane flow only. |
| Density range | 0–250 veh/mi/lane normal | Negative or extreme density fails. |
| q-k-v consistency | median relative error <= 0.10; 95th percentile <= 0.25 | `q ≈ k × v`; unit consistency gate. |
| Effective lane sanity | derived lanes between 2 and 6 for LA freeway cases | GMNS/OSM lanes are a prior, not ground truth. |
| Duplicate detector profile | no byte-identical speed/flow profiles unless physically justified | Catches copied/imputed station artifacts. |
| Missing-data gap | no queue episode may bridge >=15 min unknown gap without flag | Unknown is not congested. |

---

## 4. Average-weekday pattern gates

Average weekday should be computed from Monday–Friday only, excluding holidays and excluded incident/event days when the benchmark is intended to represent recurrent conditions.

| Gate | Recommended threshold | Notes |
|---|---:|---|
| Weekday filter correctness | 100% | Saturday/Sunday cannot enter average-weekday benchmark. |
| Same sensor set | 100% or documented | Reference and reproduced average must use the same detector/TMC set. |
| Same time resolution | 5-min PeMS; 15-min INRIX if source is 15-min | Do not compare 5-min vs 15-min without resampling note. |
| Speed MAE vs benchmark | <= 10 mph hard gate; <= 5 mph preferred | Any corridor-period with MAE >10 mph is FAIL. |
| Peak-period speed MAE | <= 8 mph preferred; <=10 mph maximum | AM/PM separately. |
| Time-of-min-speed error | <= 30 min; <=15 min preferred | For each corridor-period. |
| Congestion-duration error | <= 30 min or <=20%, whichever is larger | Compare observed/reference vs reproduced. |
| Onset time T0 error | <= 30 min | For recurrent average weekday. |
| Clearance time T3 error | <= 30 min | For recurrent average weekday. |
| Correlation of speed profile | R >= 0.80 preferred; R >= 0.70 minimum | By corridor-period average profile. |
| Space-time heatmap consistency | no reversed queue wave; no disconnected artificial blocks | Human-panel gate required. |

---

## 5. Queue and bottleneck gates

| Gate | Recommended threshold | Notes |
|---|---:|---|
| Valid episodes per sensor-period | >= 5 minimum; >=10 preferred | Otherwise label INSUFFICIENT DATA. |
| Valid episode share | >= 5% minimum, but not alone sufficient | Current code has this weak gate; keep but supplement. |
| Min congested speed | must be below `v_c`; severe if below 0.5 `v_c` | Do not call free-flow a queue. |
| Queue duration P | >= 30 min for valid μ/QVDF episode | Shorter episodes may be reported but not used for calibration. |
| Boundary truncation share | <= 20% after MDPM merge | More means period split is damaging the physics. |
| MD→PM merge | required when queue crosses 16:00 | Do not estimate μ from mid-queue. |
| Queue wave direction | median confidence >= 0.70 preferred; >=0.50 minimum | Direction gate must be day-specific and multi-bottleneck aware. |
| Queue length nonnegative | 100% | Tail/head ordering cannot be inverted. |
| Bottleneck location stability | recurring bottleneck location within 1–2 detectors across weekdays | Otherwise classify as event/uncertain. |
| Active/passive classification | active bottleneck must have local downstream discharge/capacity evidence | Avoid labeling passive queue as bottleneck. |

---

## 6. FD / S3 / traffic-flow model gates

| Gate | Recommended threshold | Notes |
|---|---:|---|
| FD fit R² for PeMS | >= 0.70 minimum; >=0.80 preferred | Applies only to measured volume cases. |
| Free-flow speed `v_f` | 55–80 mph normal for freeway cases | Flag outside range. |
| Speed at capacity `v_c` | 35–60 mph normal | Must be below `v_f`. |
| Capacity C | 1,500–2,300 vphpl normal | Flag outside range; FAIL extreme values unless justified. |
| Discharge rate μ | 1,300–2,100 vphpl normal | Corridor-specific review allowed. |
| μ/C ratio | 0.85–0.98 preferred; 0.80–1.05 review band | Outside review band FAIL unless incident/lane closure documented. |
| Critical density | plausible and positive | Must be consistent with `C/v_c`. |
| Speed-only INRIX mode | explicitly labeled synthetic-flow mode | Cannot claim independent FD calibration. |

---

## 7. QVDF gates

| Gate | Recommended threshold | Notes |
|---|---:|---|
| Number of fitted sensor-periods | >= 5 minimum; coverage >=70% preferred | Current gate checks only count; add coverage. |
| D/C convention | one consistent convention: demand divided by capacity in hours | No double-counting lanes or duration. |
| QVDF round-trip speed MAE | <= 10 mph hard; <=5 mph preferred | Compare QVDF simulated speed against observed average profile. |
| QVDF duration error | <=30 min or <=20% | Per corridor-period. |
| QVDF delay error | <=20–30% depending on data quality | Compare total delay/congestion exposure. |
| Parameter feasibility | all parameters inside DTALite/C++ feasibility ranges | Values clipped by feasibility rules must be reported. |
| Bootstrap CI width | parameter CI not excessively wide | Wide CI means insufficient data or unstable fit. |
| Prior-shrinkage flag | any parameter dominated by prior must be reported | Do not hide weak-data fits. |

---

## 8. CPI/CBI ranking gates

If the tool claims to be CPI/CBI, not only QVDF calibration, it must output ranking artifacts.

| Gate | Recommended threshold | Notes |
|---|---:|---|
| Bottleneck score table exists | required | One row per corridor/direction/period/link or bottleneck object. |
| Bottleneck ranking table exists | required | Include rank, score, duration, severity, queue extent, confidence. |
| Top-k overlap with benchmark | top-3 overlap >= 2/3; top-5 overlap >= 4/5 preferred | For prior-reviewed benchmark corridors. |
| Spearman rank correlation | >=0.70 preferred | Compare with previous benchmark ranking. |
| Worst-corridor sanity | I-395 NB should remain the worst NVTA benchmark corridor unless data/version changed | Prior benchmark note: I-395 NB had 19/23 congested links. |
| VA-7 EB sanity check | should reproduce strong PM match if using same NVTA reference | Prior note: 100% TMC match, approx. 1.9 mph speed MAE, PM R² around 0.99. |
| Active vs passive bottleneck labels | required | Do not rank passive queued links as active bottleneck heads without evidence. |

---

## 9. Case-specific gates

### I-10 QVDF paper benchmark

- Reproduce the selected paper tables/figures/statistics before claiming success.
- Required outputs: speed profile, congestion duration, queue profile, FD/QVDF parameters, observed-vs-QVDF panel.
- For the four-detector paper corridor, reproduce Tables 5–8 and Figures 8–17 or provide a row-by-row exception report.
- Any speed MAE above 10 mph is FAIL.
- Congestion duration error above 30 min or 20% is FAIL unless the input date range intentionally changed.

### I-405 California / PeMS benchmark

- Must include PeMS station list, detector ordering, station-to-link mapping, lane audit, observed fraction, and imputation-mask handling.
- Required outputs: per-day queue episodes, average weekday speed/flow/density heatmaps, FD fit, μ validation, QVDF verification, bottleneck ranking.
- For the legacy I-405 PM benchmark with 22 sensors/links, reproduce the reference state trajectories or explain mismatch.
- Any copied/imputed detector treated as measurement is FAIL.
- Capacity outside 1,500–2,300 vphpl or μ/C outside review band must be flagged.

### I-395 NVTA benchmark

- Must report NB/SB and SOV/HOV separately where applicable.
- Must compare observed INRIX/RITIS speed profile against QVDF speed profile.
- Must output corridor-level CBI measures, bottleneck event/ranking, queue and reliability summaries, and validation summaries.
- Must preserve corridor identity and TMC-to-GMNS confidence.
- I-395 NB worst-corridor ranking is a key sanity check unless the benchmark version changed.

---

## 10. Required benchmark comparison table schema

Each row should be one case × corridor × direction × period × statistic.

Required columns:

- `case_id`
- `corridor`
- `direction`
- `facility_group` such as GP/HOV/SOV if applicable
- `period`
- `date_range`
- `statistic_name`
- `reference_source`
- `reference_value`
- `new_value`
- `absolute_error`
- `relative_error_pct`
- `tolerance`
- `status` = PASS / REVIEW / FAIL / INSUFFICIENT_DATA
- `notes`

---

## 11. Required plots per benchmark case

For every I-10, I-405, and I-395/NVTA case:

1. Raw observed speed heatmap.
2. Cleaned speed heatmap.
3. Average weekday speed profile.
4. Observed vs reproduced/QVDF speed profile.
5. Queue episode panel with T0/T2/T3.
6. Queue profile / queue length panel.
7. FD q-k-v scatter and fitted curve for PeMS.
8. μ/C distribution by period.
9. Bottleneck ranking map/table.
10. Pass/fail gate summary panel.

---

## 12. Overall decision logic

- ACCEPT: all evidence gates pass; no hard physics failures; benchmark speed MAE <=10 mph; CPI/CBI ranking exists and matches prior benchmark within tolerance.
- REVIEW: minor gaps, limited data coverage, or explainable case-specific deviations.
- FAIL: missing dataset/output evidence, private paths, no benchmark comparison, speed MAE >10 mph, broken q-k-v consistency, imputed data treated as observed, missing CPI/CBI ranking, or QVDF outputs not traceable to benchmark corridors.
