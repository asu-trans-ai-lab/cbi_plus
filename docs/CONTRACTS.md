# CONTRACTS — the six input/output contracts (development specification)

Nothing enters calibration without a contract; nothing leaves without its
labels. These six contracts are the development spec that keeps the platform
stable across PeMS / INRIX / NVTA / TFB / paper-benchmark sources. Where a
contract is already enforced in code, the enforcing module is named.

## 1. Corridor contract

| Field | Requirement | Enforced by |
|---|---|---|
| corridor_id | e.g. `I10_E`, `I405_N`, `I395_NB` | loaders |
| source | `PeMS` / `INRIX` / `NVTA` / `TFB` / `paper_benchmark` | `source_format` column |
| direction | uniform EB/WB/NB/SB | sensor tables |
| detector/link order | upstream→downstream, explicitly stated | `road_order` (required by stage 1 wave check, stage 6, PINN/CTM coupling) |
| milepost / postmile | sortable | `Abs_PM` / `milepost` |
| lane_count | required; **map lane tags are priors, not truth** | v4 `detector_chain_fd` (shipped) or p99-flow inference (TFB adapter) |
| facility type | freeway / managed / HOV / GP | metadata |
| merge/diverge annotation | ramps, weaves, lane drops marked | network tables (v4 `link.csv`); needed for bottleneck-type context |

## 2. Observation contract

| Field | Requirement | Enforced by |
|---|---|---|
| timestamp | timezone explicit, fixed cadence (5 or 15 min) | loaders regrid to 5-min |
| speed_mph | fixed unit (loaders convert km/h at ingest) | `io_unified` |
| flow | per-lane vs total stated; stored per-lane | adapters |
| density | computed q/v if absent, and labeled as computed | adapters |
| occupancy | optional (PeMS) | — |
| is_observed | real measurement vs imputed | **imputed cells blanked at ingest** (tfb/v4 adapters) |
| quality_flag | missing / imputed / duplicated / abnormal | stage-1 QC columns |
| detector_status | active / failed / unreliable | stage-1 per-sensor pass rate |

**The hard rule: imputed data is never used to calibrate FD/QVDF.**
(Violating this produced byte-identical FD fits and 9,443-vphpl capacities —
see LESSONS_LEARNED #8.)

## 3. Period contract

| Period | Hours | Meaning |
|---|---|---|
| AM | 06:00–10:00 (48 five-min bins, indices 0–47) | analysis window |
| MD | 10:00–16:00 (72 bins) | analysis window |
| PM | 16:00–20:00 (48 bins) | analysis window |
| MDPM | 10:00–20:00 | merged label when one queue crosses 16:00 |

Periods are **analysis windows, not physical events**. Episode indices are
period-relative (`PERIOD_SLICE_BOUNDS`, `period_hour_mask`). Every output
declares its aggregation level: single-day episode / weekday average profile /
sensor-period statistic / corridor-period aggregate (the `aggregation_level`
column in stage-6 CSVs is the pattern to copy).

## 4. Congestion-diagnosis contract

Every congestion episode outputs:

| Field | Meaning | Enforced by |
|---|---|---|
| T0 / T2 / T3 | onset / worst point / clearance | stage 2 scan |
| P | queue duration (hours) | stage 2 |
| min_speed (v_t2) | minimum observed speed | stage 2 |
| speed_drop | relative to v_c / free-flow | derived |
| queue_length | spatial extent (dashboards' spillback note; fluid-queue view) | dashboards / CBI Lab |
| wave_direction | upstream propagation confirmed | stage-1 direction check |
| bottleneck_type | **active / passive / spillback / incident / artifact** | stage 6 classes (+ regime taxonomy) |
| confidence | diagnosis confidence | validity flags, reliability class |

**Low speed is not a bottleneck. The deliverable is the congestion
mechanism, not a speed map.**

## 5. Traffic-flow-model contract

| Field | Requirement | Enforced by |
|---|---|---|
| FD type | S3 / triangular / other — stated; zoo comparison available | stage 3 + `fd_model_zoo` |
| capacity C | explicit units (veh/h/lane) | stage 3 |
| discharge μ | explicit units; discharge-window median | stage 4 (one canonical implementation) |
| μ/C | active bottleneck typically < 1 (0.85–0.98 band) | benchmark_gates |
| v_c | speed at capacity | stage 3 / priors |
| D/C | **declared in HOURS — never presented as a plain ratio** | GLOSSARY + table headers |
| QVDF parameters | mapped to paper symbols (f_d/n/f_p/s ↔ Q_cd/Q_n/Q_cp/Q_s) | GLOSSARY two-dialect table |
| FD R² | gated (≥ 0.70) | quality gates |
| QVDF speed MAE | **≤ 10 mph hard gate** | benchmark_gates |

## 6. Benchmark contract

Every benchmark case ships:

```
data/ (complete, native format)      figures/
reproduce_<name>.py                  qvdf outputs where applicable
expected/keyed statistics            benchmark_comparison_report.csv
validation tolerances                pass_fail_summary.csv
```

Required coverage:

| Benchmark | Purpose | Status |
|---|---|---|
| I-10 | reproduce the QVDF paper benchmark | ✅ exact (Tables 5/6/7) |
| I-405 | reproduce the CA/PeMS freeway congestion case | ✅ (case study 2 + Mar-2018 run) |
| I-395 / NVTA | reproduce the planning-level QVDF / bottleneck-ranking case | ✅ (runs in outputs/; data private, linked) |

Adding a new one: `docs/ADD_A_BENCHMARK.md` (7 steps; step 7 =
`repro_gates --run` all-PASS).
