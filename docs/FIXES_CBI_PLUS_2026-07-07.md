# CBI+ (cbi_pipeline) — issues found & fixed, 2026-07-07

Review context: applying the CBI/FD/QVDF workflow to the **TrafficFlowBench PeMS-LA
release** (I-210E, 82 detectors, June 2026) for the IEEE-competition teaching lab.
Every change below is in `clean_handoff_v2/codes/cbi_pipeline/` and is deliberately
minimal + commented at the change site. **Please review each — they alter numbers.**

---

## Issue 1 — Period-relative indices applied to full-day frames  ★ CRITICAL

**Files:** `stage4_mu_validation.py` (`mu_episode`), `stage4_verification.py`,
`stage5_verification.py`

**What happened.** Stage 2 detects episodes inside each *(sensor, date, PERIOD)*
slice, so `t0/t2/t3_index` and `discharge_{start,end}_idx` are **period-relative**
(index 0 = 06:00 for AM, 16:00 for PM). Stages 4/5 rebuilt a **full-day** frame
(index 0 = 00:00) and `iloc[]`-ed those indices into it.

**Observed symptom (how it was caught).** On I-210E the audited μ median came out
**306 vphpl** — physically absurd (freeway discharge ≈ 1,700–2,000). A PM episode's
"discharge window" was being read at **00:00–03:25 — midnight flows**. Every
period-split PeMS run is affected; `t0_time/t2_time/t3_time` in
`stage4_verification.csv` were likewise offset (printed 00:00 for a 16:00 onset).

**Fix.** In all three places, slice the day frame down to the episode's period
(reusing stage-2's own `_period_for_timestamp`) before any positional lookup.

**Action item for prior runs:** any μ / verification numbers produced by v2 with
`by_period=True` (the default) should be regenerated. (The AZ I-17 sample numbers
in the skill/docs may need re-checking too.)

---

## Issue 2 — OSM/GMNS lane counts unreliable → per-lane flows wrong  ★ HIGH
*(adapter-side; no pipeline change)*

**File:** `codes/tfb_adapter.py` (the TrafficFlowBench bridge, new)

**What happened.** The GMNS network shipped with the benchmark inherits OSM lane
tags. Station 770578 sits on a link tagged `lanes=2` while measuring **5,136 veh/h
total** — 2,568 vphpl "per lane", above physical capacity. OSM lane tags on LA
freeways are frequently wrong or refer to a different cross-section.

**Fix.** The adapter now derives **effective lanes from the data itself**:
`lanes = clip(round(p99(total 5-min flow) / 2000), 2, 6)` — anchored on ≈2,000
vphpl at the 99th percentile. The GMNS tag is preserved as `gmns_lanes` in the
sensor meta for audit.

**Lesson for the pipeline generally:** treat map-derived lanes as a *prior*, not
ground truth, whenever measured volume is available.

---

## Issue 3 — Episode detector: silent fallback + fragile scan  ★ MEDIUM

**File:** `stage2_episodes.py`

**3a — provenance.** `_import_student_detector()` silently fell back to the
built-in detector when `Part1_fd_calibration.py` is absent (it *is* absent in
clean_handoff_v2). A silent detector swap is an audit hazard: results change with
no trace. → Now prints once which detector is in use.

**3b — scan hardening (fallback only; the imported student detector is untouched).**
Two failure modes in the boundary scan:
- **NaN gaps counted as congested.** `sp[j] > v_c` is False for NaN, so the scan
  walked *through* missing-data gaps, extending episodes across them. → A run of
  ≥ 3 consecutive NaN bins now ends the episode (a gap is *unknown*, not congested).
- **Single-bin blips split episodes.** One noisy 5-min sample above v_c terminated
  the scan. → The boundary must now be **sustained for 2 consecutive bins** (10 min).

**Verification:** 5 synthetic unit cases (textbook / blip / sustained recovery /
NaN gap / free-flow) all pass — see `FIXES` appendix commands below.

---

## Issue 4 — Event z-score baseline ignored the period  ★ MEDIUM

**File:** `stage2_episodes.py` (second pass in `run_episodes`)

**What happened.** The severe→event reclassification computed each sensor's P
median/MAD across **all** its episodes — AM, MD and PM mixed. PM durations are
structurally 2–4× AM durations, so the pooled baseline (a) inflates the MAD and
(b) biases the median, masking true event days and tilting period comparisons.

**Fix.** Baseline is now per **(sensor_uid, period)** — the same period-awareness
rule as Issue 1. With a 28-day window each period still has ~20 weekday episodes,
comfortably above the 5-episode minimum.

---

## Issue 5 — Direction gate assumes ONE bottleneck, whole-window  ★ MEDIUM (design)

**File:** `stage1_qc.py` (`speed_wave_direction_check`, now v2.1)

**What happened.** The gate took the single earliest speed drop of the **entire
multi-week window** as "the" bottleneck and demanded monotone upstream first-drop
ordering across the whole corridor. Two structural problems: (a) "first drop over
a month" mixes waves from different days; (b) long corridors carry **several**
bottlenecks. Empirically on I-210E June 2026 there are **16 distinct daily
first-drop winners** clustered at mileposts ≈ 1 / 14 / 17 / 24 / 32 — the gate
returned 0.375 (< 0.5 FAIL) on a physically healthy corridor.

**Fix (v2.1, same signature and return shape).**
- Evaluate **per day**, report the **median** day confidence.
- Per day, every **local minimum** of the first-drop profile is its own bottleneck
  with its own upstream catchment (segment-aware walk to the midpoint toward the
  next upstream candidate).
- **Blind-spot guard:** if nothing upstream of a head ever dropped (the empty-test
  case, previously silent), a contiguous *forward-moving* wave (first-drop time
  increasing downstream, slope > 1 bin/sensor) scores 0 — the reversed-map
  signature the gate was built to catch.

**Verification (synthetic):** healthy two-bottleneck corridor 0.93 (old: fail);
reversed-map corridor 0.00 (old: NaN — silent); uncongested NaN (unchanged).

---

---

# Round 2 — issues from the independent per-period result review

An independent review agent audited the corrected I-210E run (478 episodes,
AM/MD/PM) and the panels. Its HIGH findings drove these additional fixes.

## Issue 6 — MD→PM boundary queues truncated; MD "discharge" was mid-queue  ★ HIGH

**File:** `stage2_episodes.py` (+ `schemas.py`), review finding F5

**Evidence.** 84% of valid MD episodes ended pinned at the 16:00 boundary; 95% of
PM episodes started already congested; panels showed "discharge windows" where
speed was 20–25 mph *and falling*. This is not an edge case on a chronic corridor
— it is the norm, and it contaminates μ (MD μ/C median 0.79, below the physical
0.85–0.95 band) and truncates P/D.

**Fix.** New **boundary-merge pass**: when the same (sensor, date) has an MD
episode pinned at its last index AND a PM episode pinned at its first, the
10:00–20:00 window is re-scanned as ONE stitched episode labelled **MDPM**; the
two constituents remain in the CSV for audit but are de-validated. New
`PERIOD_SLICE_BOUNDS` (+ `period_hour_mask`) in `schemas.py` lets every
downstream slicer handle the merged label; the Issue-1 patches were reworked to
hour-bounds slicing accordingly.

## Issue 7 — stage2b computed a DIFFERENT μ (full-day indices again)  ★ HIGH

**File:** `stage2b_measured_diagnostics.py`, review finding F4

**Evidence.** stage2b's μ was uncorrelated with stage 4's (corr −0.01, ratio
~4.3×) → its "78% mu_starved outliers" verdict was pure artifact. Root cause: a
**duplicated re-implementation** of the μ computation that still indexed the
full-day frame (the Issue-1 bug pattern, copy-pasted).

**Fix.** The duplicate loop is deleted; stage2b now calls
`stage4_mu_validation.mu_episode` — one canonical, period-aware implementation.
Lesson: physics quantities must have exactly one implementation.

## Issue 8 — stage5_qvdf D/C units wrong → duration model NaN in 100% of rows  ★ HIGH

**File:** `stage5_qvdf.py`, review finding F1

**Evidence.** `qvdf_params__*.csv` had `f_d`/`n_exp`/`P_r2` NaN in 246/246 rows.
Root cause: `D_over_C = demand / (C × P_hours × lanes)` — (a) demand is already
per-lane (lanes double-counted), (b) normalizing by P_hours collapses D/C to the
rate μ/C ≤ 1, so the fit's own `doc > 1.05` guard rejected every episode. The
module's other thresholds (D/C ∈ [0.5, 3.0]) are written for the HOURS
convention, confirming the intent.

**Fix.** `D_over_C = demand_veh / capacity_vphpl` (hours), matching
`stage5_verification` and the C++ scan convention.

## Issue 9 — verification panels covered only MD  ★ LOW

**Files:** `stage4_verification.py`, `stage5_verification.py`, review finding F8

Panels were picked by global P_min ranking, and the 6-hour MD period owns the
longest episodes — all 24 panels were MD; PM (72% of the valid set) had zero
visual coverage. Fix: per-period interleave (round-robin by within-period rank).

## Issue 10 — imputed benchmark data ingested as measured  ★ HIGH (data, adapter-side)

**File:** `tfb_adapter.py`, review findings F2/F3/F9/F12

**Evidence.** 11 sensors with byte-identical FD fits; capacities of 840 and
9,443 vphpl; q≠k·v cells. Root cause is the **TrafficFlowBench release itself**:
missing stations are imputed by copying neighbors (`is_observed=False`), and the
adapter ingested imputed series as measurements — duplicate series → duplicate
FD fits → garbage capacities.

**Fix.** Adapter now blanks `is_observed=False` cells and drops stations with
< 60% observed data. **Benchmark-side recommendation:** competition participants
must be told to respect `is_observed`; consider shipping the imputation mask in
the quick-start.

## Non-issues from the review (by design; documented)

- **F13 (Saturday in "weekday")**: `apply_day_filter("weekday")` correctly drops
  weekends. Stage-4's audit set includes weekends by design (μ is day-agnostic),
  and the `difficult` filter deliberately draws the worst-decile P from ALL days.
- **F6 (Q_n snap-to-default destroys round-trip on clipped episodes)**: verbatim
  C++ `check_feasible_range` behavior — a Simon design decision. Note that most
  clipped episodes were boundary-truncated MD ones; after the Issue-6 merge their
  raw Q_n should fall back inside range. Re-check after rerun.

## Known limitation (documented, NOT changed) — period-edge truncation at 10:00 / 20:00

The Issue-6 merge stitches the dominant MD→PM edge. Queues crossing 10:00 (AM→MD)
or alive past 20:00 (PM→NT) are still truncated; the same merge pattern can be
extended if a corridor shows it (count `t0_index==0` on MD, `t3_index==last` on PM).

---

## Repro / verification commands

```powershell
# from clean_handoff_v2/codes/

# unit-test the hardened fallback detector (5 cases)
python - <<'PY'
import numpy as np
from cbi_pipeline.stage2_episodes import _fallback_detector
vc=45.0
sp=np.array([60.0]*20+[30,28,25,24,25,27,30,33,36,40,42,44]+[44]*8+[60.0]*20)
assert _fallback_detector(sp,sp*0,sp*0,vc,5)["t0_index"]==20
sp2=sp.copy(); sp2[30]=50.0   # blip must not split
assert _fallback_detector(sp2,sp2*0,sp2*0,vc,5)["t3_index"]==39
PY

# full corrected run on the TrafficFlowBench corridor
python tfb_adapter.py I-210E 2026-06-01 2026-06-28

# gate + audit medians to eyeball afterwards
#   mu_obs_vphpl median should be ~1,400-1,900 (was 306 pre-fix)
#   PM t0_time should print ~16:xx-18:xx (was 00:xx pre-fix)
```
