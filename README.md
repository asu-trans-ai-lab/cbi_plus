# CBI+ — Congestion Bottleneck Identification / FD / QVDF calibration pipeline

A general-purpose, per-corridor calibration toolkit for the four-layer
traffic-engineering pipeline:

**C**ongestion **B**ottleneck **I**dentification → **F**undamental **D**iagram →
discharge-rate **μ** validation → **QVDF** (Queue Volume-Delay Function) forward model

Given a corridor of detectors (speed + optional volume, 5-minute cadence), CBI+
answers, per detector × day × period (AM / MD / PM):

| Question | Output |
|---|---|
| *When did congestion start / peak / clear?* | queue object **T0, T2, T3** + duration **P** |
| *How bad?* | lowest speed **v_t2**, regime ∈ {uncongested, mild, recurring, severe, event} |
| *What does the bottleneck actually serve?* | discharge rate **μ** = median flow while the queue drains |
| *How much capacity was lost?* | **μ/C** — the capacity drop (typically 0.85–0.95) |
| *Can two numbers reproduce the day?* | QVDF elasticities (Q_n, Q_s, Q_cd, Q_cp) + closed-form v(t) |
| *Is any of this trustworthy?* | quality gates + per-episode audit panels (PNG) |

Handles both **PeMS** (speed + measured volume → real S3 FD fit) and **INRIX TMC**
(speed-only → volume synthesized via the CBI inverse-S3 prior).

## Install / run

```bash
pip install pandas numpy scikit-learn matplotlib pyarrow

# CA PeMS corridor (measured volume)
python -m cbi_pipeline.corridor_workflow --corridor 5-N --source pems

# AZ INRIX TMC corridor (speed-only, CBI inverse-S3 synthesis)
python -m cbi_pipeline.corridor_workflow \
    --corridor I-17 --source inrix \
    --inrix-folder <path>/I-17 \
    --s3-prior az_tmc_i17 --rederive-kc-and-m
```

Outputs per corridor: `stage1_qc/ … stage5b_corridor/`, FIXED-layout `figures/`,
per-episode verification `panels/`, and `quality_gates.json` (PASS/FAIL).

## TrafficFlowBench (IEEE competition) bridge

`tfb_adapter.py` runs the full pipeline directly on the **TrafficFlowBench**
PeMS-LA release (parquet detector states + GMNS network):

```bash
python tfb_adapter.py I-210E 2026-06-01 2026-06-28
python tfb_teaching_extract.py     # emit the CBI-Lab teaching payload (data.json)
```

The adapter derives effective lanes from the data (never trust map lane tags),
respects the release's `is_observed` imputation mask, and feeds the standard
pipeline. The extracted payload drives the **CBI Lab** interactive teaching page
(gui4gmns → TrafficFlowBench → CBI Lab): raw space-time field → identified queue
objects → physical queue under the microscope → corridor law.

Start with **[docs/TFB_CBI_GUIDE.md](docs/TFB_CBI_GUIDE.md)** — how to run, what
to read in which order, healthy magnitudes, per-period interpretation, pitfalls.

## The five stages

| Stage | Module | Produces | Outlier mitigation |
|---|---|---|---|
| 1 QC | `stage1_qc` | `qc_pass`, cleaned speed | Hampel MAD, jump, spatial-neighbor, per-day multi-bottleneck wave-direction check |
| 2 Episodes | `stage2_episodes` | queue objects per (sensor, day, period) + MD→PM boundary merge | per-(sensor, period) z-score event flag; NaN-gap + persistence hardened scan |
| 2b Screen | `stage2b_measured_diagnostics` | physical-violation flags on measured D/C, μ, V_t2 | Huber residuals |
| 3 FD | `stage3_fd_robust` | per-sensor S3 fit (capacity, v_c) + bootstrap CI | Huber loss, regime-separated |
| 4 μ | `stage4_mu_validation` + `stage4_verification` | μ per episode/link + step-by-step audit CSV/panels | discharge-window median, group shrinkage |
| 5 QVDF | `stage5_qvdf` + `stage5_verification` + `stage5b_corridor_aggregate` | elasticities per (sensor, period) + exact round-trip audit + corridor law with bootstrap CI & prior shrinkage | IQR, feasibility ranges (C++ verbatim) |

## Provenance & audits

Ten issues were found and fixed during the 2026-07 TrafficFlowBench integration
(period-relative indexing, D/C units, imputed-data ingestion, single-bottleneck
direction gate, …) — every one documented with evidence and root cause in
**[docs/FIXES_CBI_PLUS_2026-07-07.md](docs/FIXES_CBI_PLUS_2026-07-07.md)**. Read
it before comparing against pre-fix outputs. The design lesson running through
all ten: *physics quantities get exactly one implementation, indices carry their
frame with them, and priors (maps, imputation) are never treated as measurements.*

## Teaching cases

Four self-contained scripts under `teaching_cases/` (AZ I-17 INRIX week,
CA I-10E and I-405S PeMS months, and a cross-corridor comparison). See
`teaching_cases/README.md`.

## Lineage

Successor to `clean_handoff_v1/v2` (Abbasi & Zhou, ASU) and the original CBI
tool; QVDF forms mirror the DTALite C++ `scan_congestion_duration` /
`calculate_travel_time_based_on_QVDF` flow verbatim, including feasibility
ranges. Companion visual layer: [gui4gmns](https://github.com/asu-trans-ai-lab/gui4gmns).
