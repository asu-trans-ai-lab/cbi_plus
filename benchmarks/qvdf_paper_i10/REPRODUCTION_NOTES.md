# QVDF paper — Section 5 (I-10 corridor, 4 detectors) reproduction

Reproduces the QVDF paper (Zhou, Cheng, Wu et al. 2022, *Multimodal Transportation* 100017),
**Section 5 case study 1**: I-10 corridor, detectors **139, 84, 78, 137** — Tables 5–8 and
Figures 8–17. Driven by the paper's own data + calibration in
`QVDF-E/QVDF-main/.../Python_data_preparation_and_QVDF_calibration` (the same S3→PAQ→QVDF method
as AI4TMF). Run: `python reproduce_qvdf_paper.py`.

## Validation vs the published paper (✓ = matches)

**Table 5 — fundamental diagram** (exact):
| Det | cap | uc | kc | vf | m | paper |
|---|---|---|---|---|---|---|
| 139 | 1709.2 | 51.6 | 33.1 | 70.0 | 4.5 | ✓ exact |
| 84 | 1816.5 | 53.4 | 34.0 | 70.0 | 5.1 | ✓ |
| 78 | 1586.6 | 55.9 | 28.4 | 69.6 | 6.3 | ✓ |
| 137 | 1380.6 | 50.0 | 27.6 | 70.0 | 4.1 | ✓ |

**Table 6 — congestion statistics** (exact): 1275 valid days, 992 with P>0, 78 %, avg P 4.48 h.

**Table 7 — calibrated coefficients** (exact, matches Fig 10/11/12 titles):
| Det | f_d | n | f_p | s | α | β |
|---|---|---|---|---|---|---|
| 139 | 1.4307 | 1.0566 | 0.3529 | 1.1442 | 0.2836 | 1.2089 |
| 84 | 1.3653 | 1.1387 | 0.2318 | 1.6419 | 0.2062 | 1.8697 |
| 78 | 1.1273 | 1.2163 | 0.1072 | 2.0995 | 0.0735 | 2.5536 |
| 137 | 1.7290 | 1.0191 | 0.2100 | 1.7131 | 0.2862 | 1.7458 |
(α = (8/15)·f_p·f_d^s, β = n·s — verified.)

**Table 8 — curvature γ** (~1 %): e.g. 139-Friday reproduced D/C 3.86, P 5.96, v_t2 13.18,
v_bar 20.00, γ 3.59 vs paper 3.82 / 5.90 / 13.27 / 20.12 / 3.56. γ = 64·μ·(L/uc)·f_p·P^(s−4),
with v_t2/v_bar/P the *estimated* values at each weekday's mean D/C.

**Fig 9 — distributions** (P>0 days): mean P 4.48, demand 4642, D/C 2.83, QDF 0.28 — matches the
paper (4.48 / 4642 / 2.8 / 0.28).

| Figure | content | status |
|---|---|---|
| Fig 8 | volume-speed FD + S3 curve (4 det) | reproduced |
| Fig 9 | distributions P / demand / D/C / QDF | means match |
| Fig 10 | D/C vs P, mean circles + curve | reproduced |
| Fig 11 | P vs magnitude of speed reduction | reproduced |
| Fig 12 | D/C vs avg congested speed | reproduced |
| Fig 13 | γ vs D/C (4 det + reference) | reproduced |
| Fig 14–17 | observed vs estimated speed, det 84, Mon–Thu | reproduced (trough ~14 mph) |

## AI4TMF alignment — VERIFIED to regenerate the paper coefficients (maxerr 0.0000)
The exact paper recipe is in `model_vdf_calibration._vdf_calculation_stepwise`. Applying it
regenerates Table 7 to machine precision for all 4 detectors:
```
139: f_d 1.4307/1.4307  n 1.0566/1.0566  f_p 0.3529/0.3529  s 1.1442/1.1442   (regen/paper)
84 : 1.3653  1.1387  0.2318  1.6419
78 : 1.1273  1.2163  0.1072  2.0995
137: 1.7290  1.0191  0.2100  1.7131                         maxerr = 0.0000
```
The recipe (3 things the teaching `AI4TMFfit3.27.py` got wrong):
1. **Trim high-P outlier days**: keep only P ≤ mean(P)+std(P) before fitting.
2. **Pivot by exact congestion duration P, fit on the MEANS** (the red circles) with
   `curve_fit(a·x^b)`, bounds `[0,10]` — NOT `differential_evolution` on the raw daily scatter,
   and NOT the teaching s-bound `[4.1, 6.5]`.
3. **β = n·s** (the teaching `derive_qvdf_series` had β = n−s).

These are now patched into `AI4TMF_I395/AI4TMFfit_I395.py` (the version to apply to NVTA):
`analyze_paq_model` uses the threshold-trim + pivot-by-P + `curve_fit` recipe, and
`derive_qvdf_series` uses β = n·s. For an end-to-end independent regeneration on raw I-10 data,
also set the congestion cutoff to **49 mph (0.7·v_f)** and the analysis window to **7:00–21:00**
(the paper's settings) so the per-day P / D/C / v_t2 extraction matches.
