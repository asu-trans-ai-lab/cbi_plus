# CBI+ closeout — the evidence contract

A run is **delivered** only when it ships evidence, not just code. This page
defines the contract (adopted from the 2026-07-08 external review; gate
thresholds in `benchmarks/benchmark_validation_tolerance_template.csv` and
`benchmarks/GATES_MEMO.md`).

## What a delivered corridor run contains

```
<run_dir>/
    quality_gates.json                      pipeline gates (stage 1-5)
    stage2_episodes/episodes_per_link_day.csv
    stage4_verification/  + panels/         per-episode audit (steps A-G)
    stage5_verification/  + panels/         QVDF round-trip audit (R1-R5)
    stage5b_corridor/link_qvdf_corridor.csv corridor law w/ CI + shrinkage
    stage6_cbi/
        benchmark_bottleneck_ranking.csv    THE CPI/CBI deliverable (ranked)
        benchmark_CBI_corridor_summary.csv
    benchmark_gates/
        pass_fail_summary.csv               every gate x period: PASS/FAIL/REVIEW
        benchmark_comparison_report.csv     current vs reference stats
```

Produce the last two blocks for any run:

```bash
python -m cbi_pipeline.benchmark_gates <run_dir> [--reference <previous_run_dir>]
# stage6 runs automatically inside corridor_workflow; standalone:
# stage6_cbi_ranking.run_ranking(episodes_df, corridor, out_dir)
```

## The three benchmark cases (reproduce before any release)

| Case | Data (in repo) | Command |
|---|---|---|
| **I-10 QVDF paper** (PeMS, Mar 2018, 32 sensors) | `benchmarks/I-10/` | `python -m cbi_pipeline.corridor_workflow --corridor 10-E --source pems --pems-path benchmarks/I-10/link_performance.json` |
| **I-405 CA PeMS** (Mar 2018, 29 sensors) | `benchmarks/I-405/` | same with `benchmarks/I-405/...` and `--corridor 405-N` |
| **I-395 NVTA** (INRIX, private — path in outputs/DATASETS.md) | not in repo | `--source inrix --inrix-folder <NVTA path>` |

`benchmarks/MANIFEST.json` is the dataset manifest. Compare a rerun against a
prior accepted run with `--reference` to get Spearman rank stability and top-5
bottleneck overlap in `pass_fail_summary.csv`.

## Aggregation levels — label every number

| Level | Produced by | Example fields |
|---|---|---|
| per episode | stage 2 / stage 4 audit | T0, T2, T3, P, v_t2, mu_obs |
| per sensor-period | stage 5 QVDF fit, stage 6 score | Q_n, CBI_score, bottleneck_class |
| per link (median) | stage 4 mu validation | mu_per_link |
| corridor-period | stage 5b, stage 6 summary | Q_n_shrunk, total_CBI_score |

Every stage-6 CSV row carries an explicit `aggregation_level` column.

## Known measured-vs-synthesized caveat (from the gate results)

On speed-only INRIX corridors, μ is synthesized via inverse-S3 and
**systematically under-reads discharge during deep congestion** (μ/C ≈ 0.6-0.8
observed on I-395/I-66 vs the physical 0.85-0.98 band). Treat μ/C gates on
synthesized corridors as REVIEW, not FAIL — and never mix measured and
synthesized μ in one comparison. PeMS corridors (measured volume) must meet the
band strictly (I-210E: 0.87 ✓).
