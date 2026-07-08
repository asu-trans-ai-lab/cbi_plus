# CBI+ on TrafficFlowBench — a practical guide

How to run the **CBI/FD/QVDF calibration pipeline** (`cbi_pipeline`, a.k.a. CBI+)
on the IEEE **TrafficFlowBench** PeMS-LA release, and — more importantly — how to
*read* what it produces. Written for competition participants and students; no
prior traffic-engineering background assumed for the interpretation sections.

Companion artifacts:
- **Teaching lab (visual):** `gui4gmns docs/trafficflowbench/cbi_lab/` — the same
  run rendered as a 4-act interactive page (raw field → CBI → physical queue → law).
- **Fixes log:** `FIXES_CBI_PLUS_2026-07-07.md` — 4 issues found & fixed during
  this integration; read it before trusting older outputs.

---

## 1. What the tool answers

Given a corridor of detectors (speed + volume at 5-min), CBI+ answers, per
detector × day × period (AM 06–10, MD 10–16, PM 16–20):

| Question | Output | Where |
|---|---|---|
| *When did congestion start / peak / clear?* | *T0, T2, T3* + duration *P* | stage 2 |
| *How bad?* | lowest speed *v_t2*, regime label (uncongested/mild/recurring/severe/event) | stage 2 |
| *What does the bottleneck actually serve?* | discharge rate **μ** (median flow while the queue drains) | stage 4 |
| *How much capacity was lost?* | **μ/C** — the capacity drop (typ. 0.85–0.95) | stage 4 |
| *Can two numbers reproduce the day?* | QVDF elasticities (Q_n, Q_s, Q_cd, Q_cp) + closed-form v(t) | stage 5 |
| *Is any of this trustworthy?* | quality gates + per-episode audit panels | gates/verification |

The competition mapping is direct: stage 2's episode objects are **Task 2's
`queue_objects.csv`** schema; stage 4/5's λ, μ, N, Q, C chain is **Task 3**.

## 2. Run it

```powershell
# from clean_handoff_v2/codes/  (needs: pandas, pyarrow, sklearn, matplotlib)
python tfb_adapter.py I-210E 2026-06-01 2026-06-28
```

The adapter bridges the benchmark's parquet (`release/I-<corr>/train_detector_states.parquet`)
into the pipeline's compact JSON + sensor table, **deriving effective lanes from
the data** (p99 flow / 2,000 vphpl — do *not* trust OSM lane tags, see Fixes #2),
then runs all stages. ~10 min for 82 sensors × 28 days. Outputs land in
`clean_handoff_v2/outputs/trafficflowbench/210-E/`.

Any corridor/window works: `python tfb_adapter.py I-405N 2026-03-01 2026-03-28`.

Then extract the teaching-page payload:

```powershell
python tfb_teaching_extract.py            # writes cbi_lab/data.json for gui4gmns
```

## 3. Read the outputs — in this order

### 3.1 `quality_gates.json` first, always
PASS/FAIL per gate. *N/A and UNKNOWN are not failures.* If `valid_episode_pct`
fails, the corridor is mostly uncongested for your window — lower `--v-c` or pick
another month; don't force it.

### 3.2 `stage2_episodes/episodes_per_link_day.csv` — the census
One row per (sensor, date, period). Sanity checks that take 2 minutes:
- **Counts by period**: PM ≥ AM ≥ MD valid episodes on most urban corridors.
- **P by period**: AM median < PM median. If they're equal, suspect the scan.
- **Edge truncation**: episodes with `t3_index == 47` (AM/PM) or `71` (MD) hit the
  period boundary — their P is a *lower bound* (known limitation; see Fixes log).

### 3.3 `stage4_verification/stage4_verification.csv` — the μ audit
Every valid episode, one row, steps A–G. The two-tier sanity rule before trusting μ:
1. `mu_consistency` median < 0.10 (ours: **0.066** ✓)
2. Hand-inspect ≥ 5 panels in `stage4_verification/panels/` — do the T0/T2/T3
   verticals sit on the actual breakdown? Does the shaded discharge window cover
   the recovering tail (T2→T3)?

**Healthy magnitudes** (LA freeway, per lane): μ ≈ 1,500–1,950 vphpl; μ/C ≈
0.85–0.95; v_t2 ≈ 15–35 mph. If you see μ ≈ 300, your indices or lanes are wrong —
that exact failure happened and is documented in Fixes #1/#2.

### 3.4 `stage5_verification/stage5_qvdf_verification.csv` — the QVDF round-trip
- `P_err_pct` and `vt2_err_pct` **must be ≈ 0** (the calibration is anchored to
  reproduce them exactly). Non-zero = units bug — halt.
- `v_t_MAPE_pct` is the honest number: 30–60% is normal for the symmetric
  fourth-order queue; episodes > 100% are asymmetric (slow build / fast clear or
  spillback) — flag them, don't hide them.
- Feasibility clipping (`*_raw` vs final) firing on > 25% of episodes means too
  many barely-congested days slipped in.

### 3.5 `stage5b_corridor/link_qvdf_corridor.csv` — the corridor law
Use the `_shrunk` columns (bootstrap + prior-shrinkage protected), not `_median`.
`reliability_class` tells you whether the row is an independent calibration
(high, n≥20) or is leaning on the prior (low, n<10).

## 4. Reading per-period results (what AM vs MD vs PM tells you)

Periods are not just time filters — they are different *demand regimes*:

- **AM**: commute pulse, sharp onset, typically the *highest μ* (fresh drivers,
  no heat, incident-light). On I-210E June: μ=1,902, P=120 min, v_t2=32 mph.
- **MD**: background + discretionary demand. Lower μ (1,506) with *longer* P here
  is the signature of slow midday churn rather than a hard bottleneck pulse.
- **PM**: the structural peak — P=185 min, v_t2=21 mph, μ=1,680. This is where
  chronic bottlenecks are ranked and where the QVDF elasticities matter most.

Compare the *same sensor* across periods: a true structural bottleneck (lane drop,
merge) appears in AM **and** PM; an incident-driven one appears once. That
persistence test is the cheapest recurring-vs-non-recurring classifier you have.

## 5. Pitfalls (each one bit us; all are in the Fixes log)

1. **Period-relative vs day-relative indices.** Episode indices count from the
   period start, not midnight. Any code that `iloc[]`s them into a full-day array
   silently reads the wrong hours (Fix #1 — patched in stage 4/5).
2. **Map lanes lie.** Derive per-lane flow from measured totals with data-driven
   effective lanes; keep the map value only for audit (Fix #2).
3. **Know your detector.** The pipeline prefers the canonical Part-1 detector and
   silently used a weaker fallback when absent; it now announces which is active
   (Fix #3). The fallback additionally needed NaN-gap and blip hardening.
4. **Baselines must respect the period.** The event/outlier z-score is per
   (sensor, period); pooling AM+PM biases both (Fix #4).
5. **Units discipline.** Speeds here are stored km/h and converted to mph at load;
   D/C in the QVDF calibration is in *hours* (accumulated per-lane vehicles ÷
   hourly lane capacity). When a number looks off by ×1.6 or ×12, it's units.

## 6. One-screen cheat sheet

```
T0/T2/T3   onset / worst / clearance of a congestion episode (per period)
P          congestion duration = T3 - T0                     [min]
v_c        speed at capacity — the congested/uncongested threshold [mph]
v_t2       lowest observed speed in the episode              [mph]
μ          bottleneck discharge rate: median flow, T2→T3 window [veh/h/lane]
C          calibrated capacity from the FD fit               [veh/h/lane]
μ/C        capacity drop — an active bottleneck serves BELOW capacity (0.85-0.95)
D/C        demand-to-capacity ratio (HOURS convention in calibration)
Q_n        elasticity: how fast P grows with D/C   (P̂ = Q_cd·(D/C)^Q_n)
Q_cp,Q_s   elasticity: how deep speed falls with P (v̂_t2 = v_c/(1+Q_cp·P^Q_s))
Q(t)       fourth-order queue  ¼·γ·(t-T0)²(t-T3)²  → closed-form v(t)
```
