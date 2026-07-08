# The CBI+ stage chain — data in, decision out (one page)

Every corridor takes the same streamlined path. Each stage names its input,
its output artifact, its Excel teaching twin, and its historical ancestor
(from the four public repos, now archived under `old_github_repo/`).

```
  DATA                     STAGE                       ARTIFACT                        TEACHING TWIN (docs/teaching/)   ANCESTOR (old repo)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  PeMS json / INRIX     ┌─ 0 · load ────────────────┐  unified long df                 1_raw_data                       CBI-main cbi_reading
  RITIS / TFB parquet ─▶│  io_unified (+discover)   │  (speed/flow per 5-min,
                        └───────────┬───────────────┘   is_observed-filtered)
                        ┌─ 1 · QC ──▼────────────────┐  qc_pass, cleaned speed,        1_statistics                     (new in v2)
                        │  Hampel/jump/spatial +     │  per-day multi-bottleneck
                        │  wave-direction gate       │  direction confidence
                        └───────────┬───────────────┘
                        ┌─ 2 · episodes ─▼──────────┐  T0/T2/T3, P, demand,            3_t0 / 3_t2 / 3_t3               CBI-main scan_congestion_duration
                        │  scan + MD→PM merge +     │  regime, discharge window        4_CD_vol / 4_CD_spd
                        │  event z-score            │  (episodes_per_link_day.csv)
                        └──────┬──────────┬─────────┘
              ┌─ 6 · CBI rank ─▼──┐   ┌── 3 · FD ──▼───────┐  S3 fit + bootstrap CI    0_FD                             Traffic-Flow-FD-main (S3 + 16-model
              │ score = freq ×    │   │  Huber S3           │  capacity C, v_c                                           zoo, now cbi_pipeline.fd_model_zoo)
              │ duration ×        │   └──────────┬─────────┘
              │ severity;         │   ┌─ 4 · μ ──▼─────────┐  discharge μ, μ/C          4_CD_vol median                  QVDF-main data2supply
              │ active/passive/   │   │  window median +   │  capacity drop
              │ spillback classes │   │  step A-G audit    │  (stage4_verification)
              └──────┬───────────┘   └──────────┬─────────┘
                     │               ┌─ 5 · QVDF ▼─────────┐  Q_n,Q_s,Q_cd,Q_cp +      5_QVDF / 5_QVDF_beta_Z           QVDF-main CongestionDemandBased-
                     │               │  two-step elasticity │  exact round-trip audit;  Step1.2_QVDF (V2 workbook)       Calibration + PAQ-main (cubic
                     │               │  + 5b aggregation    │  corridor law w/ CI       6_DTA                            arrival ancestor)
                     │               └──────────┬─────────┘
                     └──────────┬───────────────┘
                     ┌─ gates ──▼────────────────┐  pass_fail_summary.csv,
                     │  benchmark_gates:         │  benchmark_comparison_report.csv
                     │  physics bands, ≤10 mph   │
                     │  MAE, ranking stability   │
                     └──────────┬───────────────┘
                     ┌─ deliver ▼────────────────┐  per-corridor dashboard (cbi_dashboard),
                     │                           │  bottleneck ranking, DEV_STATUS card
                     └───────────────────────────┘
```

## Validation anchors (all in-repo, all public)

| Anchor | Where | What it pins |
|---|---|---|
| QVDF paper Case Study 1 (I-10 Phoenix 2016) | `benchmarks/qvdf_paper_i10/` | FD + two-step calibration: Tables 5/6/7 exact, Figs 8–17 |
| QVDF paper Case Study 2 (I-405 NB 4-month) | `benchmarks/qvdf_paper_casestudy2/` | corridor-level P/v_t2/v̄ vs D/C + μ/C: Figs 19–23, R²=0.977, paper's own per-day data |
| PeMS I-10E + I-405N (Mar 2018) | `benchmarks/I-10`, `benchmarks/I-405` | full modern pipeline end-to-end, 6/6 gates |
| CTM forward example | `benchmarks/ctm_example/` | independent forward simulation cross-check |
| Teaching workbooks | `docs/teaching/` | every stage, by hand, in Excel |

## What the four old repos contributed (and what superseded them)

| Old repo | Lives on as | Superseded by |
|---|---|---|
| CBI-main | T0/T3 scan concept; ranking spec | stage 2 (hardened scan), stage 6 (freq×dur×sev + classes) |
| Traffic-Flow-FD-main | `cbi_pipeline.fd_model_zoo` (16 models, benchmark layer) | stage 3 Huber+bootstrap S3 (production fit) |
| PAQ-main | quartic td_queue lineage; theory docs | stage 5 QVDF round-trip |
| QVDF-main | both paper benchmarks + teaching workbooks + CTM | stages 3–5b (Huber, audits, shrinkage) |
```
