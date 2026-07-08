# ENGINE_SHOWCASE — every engine, one call, on competition data

For TrafficFlowBench competitors: the platform's engines are callable directly
on the v4 release (or the in-repo samples). Competitions can **cite cbi_plus**
instead of vendoring source. Evaluation focus is non-path / non-OD: the
physical gate first, then the state score (S_state = 0.40·all + 0.60·congested
cells) — every engine below serves that target.

## 0. Get corridor data (v4 adapter)

```bash
# 3-day samples of ALL FOUR corridors ship in-repo:
ls benchmarks/ieee_v4_samples/          # I405N I405S I5N I5S

# full release (set IEEE_V4_ROOT), any window, straight into the pipeline:
python ieee_v4_adapter.py I405N 2026-04-01 2026-04-28 --run
```
The v4 `detector_chain_fd.csv` ships lanes/capacity/v_cut — the adapter uses
them directly (no lane inference) and blanks `is_observed=False` cells
(imputation is never treated as measurement).

## 1. FD — fundamental diagram (production + 16-model benchmark)

```python
from cbi_pipeline import stage3_fd_robust            # production: S3, Huber + bootstrap
from cbi_pipeline import fd_model_zoo                 # 16-model comparison suite
```
Outlier filtering is built in (Huber loss; stage-1 Hampel/jump/spatial QC ahead
of it). Justify your FD choice with `benchmarks/fd_16models/reproduce_fd16.py`.

## 2. CBI — episodes and bottleneck ranking

```python
from cbi_pipeline import stage2_episodes              # T0/T2/T3 scan + MD→PM merge
from cbi_pipeline import stage6_cbi_ranking           # score = freq × duration × severity
```
Output = the queue objects the competition's Task-2 schema mirrors, plus
active/passive/spillback classes.

## 3. QVDF — the calibrated queue law

```python
from cbi_pipeline import stage5_qvdf, stage5_verification   # Q_n,Q_s,Q_cd,Q_cp + exact round-trip
```
v4 sample validation (I405N, 3 days): round-trip P/v_t2 error 0.0%, v(t) MAPE
12.2%.

## 4. PAQ — polynomial queue shapes (and the arena)

```bash
python -m cbi_pipeline.engine_arena <run_dir> --json <compact.json>
```
Newell quadratic vs PAQ cubic vs QVDF quartic vs trapezoid, per audited
episode. I-210E verdict: trapezoid 301/450 (oversaturation), quadratic 122
(mild peaks) — pick shapes per episode, not per religion.

## 5. CTM — forward simulation (basic referee)

```bash
cd engines/ctm_python && python Cell_Transmission_Model.py     # native format
```
Feed stage-5b QVDF parameters + demand to sanity-check a reconstruction
forward in time (Example 1 = the cubic-demand case).

## 6. PINN — physics-informed state estimation

```bash
cd engines/pinn_tse/src && python main.py                      # native MobileCentury format
```
The computational-graph TSE (torch). Couple via the corridor contract
(sorted links + 5-min state) when you outgrow the native demo.

## 7. Tensor / RPCA — sparse-data + anomaly AI

```python
from cbi_pipeline.tensor_tools import rpca, tensor_complete, low_rank_complete
```
RPCA splits recurrent vs anomaly (the label-free abnormal-cell view); the 3-D
cube beats per-lane completion by ~30% at low probe penetration.

## AI/ML family map — which AI applies to which dataset

| Dataset (in-repo) | AI/ML families with working adapters |
|---|---|
| v4 corridor states (`ieee_v4_samples/`, adapter) | tensor completion (masked cells), RPCA anomaly, QVDF/PAQ shape fitting, PINN (via contract), any supervised model on the long df |
| PeMS 2018 I-10/I-405 (`benchmarks/I-10`,`I-405`) | full pipeline; FD zoo; arena |
| QVDF paper cases (`qvdf_paper_*`) | elasticity calibration reference — validate your learned model against exact numbers |
| Arizona INRIX (`cbi_arizona/`) | speed-only path (inverse-S3 synthesis); cross-generation scan comparison |
| PAQ corridor (`paq_corridor/`) | shape families; physical queue extraction from speed fields |
| MobileCentury (`engines/pinn_tse/`) | PINN TSE (gps+loop+ramp fusion) |
| NGSIM (path in DATASETS.md) | 3-D cube tensor completion (space×time×lane) |

All datasets: Parquet + samples + GeoJSON in `benchmarks/_datapack/`
(`DATA_FORMATS.md` has every schema). Verify nothing broke:
`python -m cbi_pipeline.repro_gates` — currently **21/21 PASS**.
