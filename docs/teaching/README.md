# Teaching workbooks — the pipeline, by hand, in Excel

> Read [THEORY_FOUNDATIONS.md](THEORY_FOUNDATIONS.md) first — the V/C-vs-dynamics correction and the LWR→Newell→Daganzo lineage these workbooks implement.

Two Excel workbooks that walk the SAME method the `cbi_pipeline` code runs,
step by step, so a student can verify every stage against cells they can see.
Reorganized mapping below ties each sheet to its pipeline stage.

## 1. `QVDF_Teaching_V2.xlsx` (small — the concept walkthrough)

| Sheet | What it teaches | Pipeline equivalent |
|---|---|---|
| `Step1.1_FD&QVDF` | fundamental diagram + QVDF coefficients from a small sample | stage 3 (`stage3_fd_robust`) + stage 5 calibration |
| `Step1.2_QVDF` | the two-step elasticity calibration (D/C → P → speed reduction) | stage 5 (`stage5_qvdf` Eq. 25/27 recipe) |
| `Step2_Time dependent speed` | fourth-order td_queue → td_speed reconstruction | stage 5 round-trip (`stage5_verification` R5) |
| `Step_2.5`, `Step2.6_Time dependent speed` | γ curvature + weekday speed profiles | Table 8 / Figs 14–17 of the paper reproduction |
| `Step3_Link level analysis` | link-level performance assembly | stage 5b corridor aggregation |

## 2. `Fluid_Queue_Approximation_v3.0.xlsx` (full worked example, raw data → DTA)

| Sheet | What it teaches | Pipeline equivalent |
|---|---|---|
| `0_FD` | FD parameter block | stage 3 output (`stage3_fd/<sensor>.json`) |
| `1_raw_data` (100k rows), `1_statistics` | raw detector readings + day statistics | stage 0/1 (`io_unified` + `stage1_qc`) |
| `2_pivot_spd`, `2_pivot_vol`, `2_pivot_length` | day × time-of-day pivots | the space-time fields in the dashboards |
| `3_t0`, `3_t2`, `3_t3` | the congestion scan: onset / minimum / clearance per day | stage 2 episode scan (T0/T2/T3) |
| `4_CD_vol`, `4_CD_spd` | congestion-duration windows: demand + speeds inside [t0, t3] | stage 2 `demand_veh` + stage 4 discharge window |
| `5_QVDF`, `5_QVDF_beta_Z` | QVDF calibration and β/Z variants | stage 5 (`Q_n, Q_s, Q_cd, Q_cp`) |
| `6_DTA` | hand-off of QVDF parameters to a DTA run | DTALite `link_qvdf` consumption (stage 5b CSV) |

## How to use in class

1. Open the workbook next to a corridor dashboard (`outputs/dashboards/*.html`)
   or the paper-reproduction page (`benchmarks/qvdf_paper_i10/index.html`).
2. For each step, have students compute one day's T0/T2/T3/P by hand in the
   `3_*` sheets, then find the same episode in the dashboard's parameter table.
3. The two-step calibration in `Step1.2_QVDF` uses the same power-law forms the
   paper's Table 7 reports — students can check f_d/n/f_p/s against
   `benchmarks/qvdf_paper_i10/Table7_calibrated_coeffs.csv`.

Provenance: Simon Zhou's QVDF teaching series (V2, 2026) and the Fluid Queue
Approximation workbook v3.0.
