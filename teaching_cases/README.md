# Teaching cases

Four self-contained Python scripts that demonstrate every layer of the
cbi_pipeline workflow on real data.

| Script | Dataset | Runtime | What you learn |
|---|---|---|---|
| `case_01_az_inrix_i17.py` | AZ INRIX I-17 (256 TMCs, 1 week) | ~3 min | INRIX speed-only path with CBI inverse-S3 synthesis, auto-vf calibration, rural prior selection, clean week with 0 outliers, thin-AM-sample shrinkage |
| `case_02_ca_pems_i10.py` | CA PeMS I-10 East (16 sensors, 1 month) | ~2 min | Real S3 FD fit on measured volume, mid-strength structural-bias finding, multi-sensor corridor aggregation |
| `case_03_ca_pems_i405.py` | CA PeMS I-405 South (20 sensors, 1 month) | ~2 min | Chronic congestion (most days valid), informative non-finding on mu_R2 gap, long-P episodes stress-test the fourth-order queue shape |
| `case_04_cross_corridor_comparison.py` | reads outputs from cases 01-03 | ~10 sec | Side-by-side quality gate matrix + corridor-level QVDF parameter table across all three corridors |

## Run all four (recommended order)

```powershell
# from dev/ (this repo), after: pip install -e .
python teaching_cases/case_01_az_inrix_i17.py
python teaching_cases/case_02_ca_pems_i10.py
python teaching_cases/case_03_ca_pems_i405.py
python teaching_cases/case_04_cross_corridor_comparison.py
```

Each case writes to `outputs/<case_name>/<corridor>/`. Case 04 reads the
artifacts from cases 01-03 — run them first.

## What to look at after each case

| Artifact | Why |
|---|---|
| `quality_gates.json` | Anchor: did this corridor pass? Inspect every gate's value + threshold. |
| `figures/weekday__variation_1_daily__mu_pred_vs_obs.png` | The headline plot — predicted vs observed mu. |
| `stage4_verification/panels/verify__*.png` (4-panel) | Sanity-check the v_c / Capacity / P / V_t2 / v(t) audit for a few episodes. |
| `stage5_verification/panels/qvdf_verify__*.png` (6-panel) | Round-by-round QVDF audit — confirm P_err = 0% and vt2_err = 0%. |
| `stage5b_corridor/link_qvdf_corridor.csv` | Final corridor x period QVDF parameters with bootstrap CIs + shrinkage source. |
| `stage5b_corridor/figures/corridor_param_ladder.png` | Visual: median + CI + shrunk + prior for all six params. |

## When a case FAILS its quality gates

The orchestrator prints the failing gates with their values. Common patterns:

| Gate fails | Likely cause | Action |
|---|---|---|
| `mu_R2_gap_valid_vs_all` | Either chronic congestion (I-405 case) or weak mu model | Read it as a finding — most days valid is good news for that corridor |
| `qvdf_n_fitted` | Too few (sensor x period) cells with 5+ valid days | Increase max_sensors or extend the date window |
| `direction_confidence` | Bad TMC map-matching or only 1 sensor | Inspect `stage1_qc/timespace_<corridor>.png` |
| `valid_episode_pct` | Most days uncongested for this corridor | Lower the `--v-c` threshold or accept the diagnosis |

## Customizing for your own corridor

Copy any case file and edit:
```python
summary = corridor_workflow.run_corridor(
    corridor="YOUR-CORRIDOR",            # e.g. "210-W" or "I-17"
    source="pems" or "inrix",
    inrix_folder=...                     # for INRIX
    pems_path=...                        # for PeMS
    s3_prior="urban_freeway",            # or "rural_freeway" or {"vf_mph":75, ...}
    auto_calibrate_vf=True,
    rederive_kc_and_m=False,
    v_c_mph=50.0,
    v_f_mph=70.0,
    n_boot=50,
    out_root=Path("outputs/my_case"),
)
```

The available S3 prior presets are in `schemas.S3_PRIOR_PRESETS`. Pick the
one matching your facility type; the auto-vf step will fine-tune vf from the
speed data itself.
