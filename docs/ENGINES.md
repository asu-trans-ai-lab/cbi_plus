# ENGINES.md — every engine and repo in the CBI+ ecosystem

The complete registry ("we use so many engines together — don't let them get
lost"). One row per engine: where it lives NOW, its native data format (kept
as-is — integration is stage-by-stage, format conversion only when a coupling
is actually built), and its current integration stage.

**Integration stages:** ① vendored (native format, runs standalone) →
② benchmarked (reproduction page + repro gate) → ③ coupled (reads/writes the
pipeline's corridor contract) → ④ arena (plays against other engines on the
same corridor-day).

## The corridor contract (what engines couple through)

Engines that operate on a corridor need **sorted links**: the pipeline
provides `(sensor_uid, road_order, length, lanes)` from any loader
(`io_unified`), and per-(sensor, 5-min) `{speed, flow, density}`. PINN and CTM
both consume exactly this shape (PINN: cells along a corridor; CTM: ordered
cells with demand/supply) — the contract is the bridge, their internals stay
untouched.

## Registry

| # | Engine / repo | Role | Lives at | Native data format | Stage |
|---|---|---|---|---|---|
| 1 | **cbi_pipeline** (this repo) | production: QC → episodes → FD → μ → QVDF → ranking → gates | `cbi_pipeline/` | unified long df (TIMESERIES_COLUMNS) | — core |
| 2 | **CBI-main** (legacy tool, C++ + Python) | ancestor of episode scan + ranking | `old_github_repo/` (archived); benchmark: `benchmarks/cbi_arizona/` | RITIS `Reading.csv` + `TMC_Identification.csv` | ② |
| 3 | **Traffic-Flow-Fundamental-Diagram** | 16-model FD suite (S3 reference) | `cbi_pipeline/fd_model_zoo.py`; benchmark: `benchmarks/fd_16models/` | `input_data.csv` (Flow,Speed,Density) | ③ (zoo importable) |
| 4 | **Polynomial-Arrival-Queue (PAQ)** | polynomial queue shapes (quad/cubic) | `old_github_repo/` (archived); benchmark: `benchmarks/paq_corridor/`; shapes live in dashboards + arena | daily `Speed_04XX.xlsx` (Time × Postmile × AggSpeed) | ④ (shape family in arena) |
| 5 | **QVDF-main** (paper repo) | the QVDF derivation + both paper case studies + teaching Excel | benchmarks: `qvdf_paper_i10/`, `qvdf_paper_casestudy2/`; teaching: `docs/teaching/` | compact PeMS CSVs; calibration workbooks | ② (exact reproductions) |
| 6 | **CTM-Python** (Cell Transmission Model) | forward mesoscopic simulation — the physics referee | `engines/ctm_python/` (+ small QVDF-main variant in `benchmarks/ctm_example/`) | `demand.csv`, `supply.csv`, `link.csv`; emits Density/Flow profile CSVs | ① vendored (needs sorted links → contract) |
| 7 | **PINN TSE** (Traffic_State_Estimation-Computational_Graph, the JSE paper) | learning-based state estimation with physics in the computational graph | `engines/pinn_tse/` | `data/MobileCentury/{gps,loop,ramp,travel_time}.csv` (corridor cells × time) | ① vendored (needs sorted links → contract; torch dependency optional) |
| 7b | **flow_tensor (FTT engine)** | corridor-state tensor: HOSVD physical modes, Tucker price-of-rank, OD-free flow-through residual (math: docs/FLOW_TENSOR_MATH.md; NO dynamic OD) | `cbi_pipeline/flow_tensor.py` | compact JSON via any loader | ③ coupled |
| 8 | **tensor_tools** (CBI+ tensor handoff) | RPCA recurrent/anomaly split; 3-D cube completion; observability | `cbi_pipeline/tensor_tools.py` | numpy arrays [space × time (× lane)] | ③ (feeds CBI Lab evidence) |
| 9 | **DTALite** | downstream consumer: assignment with QVDF link performance | external (dtalite repos) | GMNS + `link_qvdf` CSV (stage-5b output is drop-in) | ③ (via stage-5b CSV) |
| 10 | **gui4gmns** | the visualization layer (dashboards, CBI Lab, portals) | github.com/asu-trans-ai-lab/gui4gmns | GMNS node/link + frames.json payloads | ③ (payload exporters) |
| 11 | **TrafficFlowBench** | the IEEE dataset/competition feeding all of this | external bundles | parquet detector states + GMNS (+abnormal labels) | ③ (`tfb_adapter.py`) |

## The arena — engines play against each other

`python -m cbi_pipeline.engine_arena <run_dir>` (v0) puts the queue-shape
engines head-to-head on every audited episode of a processed corridor:

- **Newell quadratic** (PAQ ancestor)
- **PAQ cubic** (skewed)
- **QVDF quartic** (the C++ canonical)
- **trapezoid** (the oversaturation shape)

Each fits the same episode's speed-deficit profile; the arena reports per-
episode winners and a corridor scoreboard (`engine_arena_results.csv`). First
result (I-210E + PAQ corridor): mild single-peak episodes → quadratic/quartic;
long oversaturated episodes → trapezoid, decisively. **The verdict is per
episode — no shape wins everywhere, which is exactly why the arena exists.**

Staged next steps (deliberately not yet built):
- CTM as forward referee: feed stage-5b QVDF parameters + demand into
  `engines/ctm_python`, compare simulated vs observed fields (its Example 1 is
  the cubic-demand case linked to the PAQ derivation).
- PINN vs tensor completion: reconstruct masked cells on the same corridor
  (PINN needs torch; tensor_tools is numpy-only) — the sparse-data duel.
- FD duel: `fd_model_zoo` (16 models, plain LS) vs `stage3_fd_robust` (S3
  Huber + bootstrap + outlier filtering) per sensor — "which sensors actually
  need robustness" as a map.
