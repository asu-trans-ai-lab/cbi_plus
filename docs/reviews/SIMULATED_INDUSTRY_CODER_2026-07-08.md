# Simulated wave 3 — RITIS engineer, INRIX engineer, staff coder (2026-07-08)

Third persona wave under the [AI Participant Protocol](../AI_PARTICIPANT_PROTOCOL.md):
two industry perspectives (the people whose data and dashboards we build on)
plus a pre-release staff-level code review that CONFIRMED bugs by running
reproductions. Dispositions below; register rows in
[../ISSUE_REGISTER.md](../ISSUE_REGISTER.md) §8 (wave 3).

## Coder review — 7 CONFIRMED bugs, all fixed in v2.4.0

| finding | disposition |
|---|---|
| C-1 `diagnose` never passed `road_order` to `run_ranking` → **bottleneck classes computed on alphabetical sensor order** (planted bottleneck flipped spillback_source → queued_passive under a rename) | FIXED — topology dict passed; adversarial-rename regression test |
| C-2 speed-only frames (the documented INRIX use case) crashed in `build_corridor_panel` (`KeyError: flow_vph`) | FIXED — flow pivot guarded |
| C-3 `t*_time` computed by arithmetic from period start → drifted across data gaps | FIXED — indices mapped through each group's actual timestamps (MDPM/all_day handled) |
| C-4 one degenerate sensor discarded every other sensor's FD fit | FIXED — NaN-fill per sensor |
| C-5 `speed_units="kmh"` skipped on pre-cleaned frames, then warned the user to do what they had done | FIXED — converts every speed column; warning suppressed when units declared |
| C-6 `load_ieee_v4` id mismatches (prefixes, float-parsed '101.0') silently degraded all road_order to -1 | FIXED — id normalization + unmatched warning / all-unmatched error |
| C-7 all-imputed v4 file returned an empty frame silently | FIXED — explicit error |
| C-8 external `Part1_fd_calibration` import from sys.path in the wheel (SUSPECTED) | OPEN (SIM-C8) — vendor-only detector for packaged builds |
| C-9 `bootstrap_fd` case-sensitive + different capacity grid than `fit_fd_huber` (SUSPECTED) | FIXED — shared `_normalize_model_name`; grid unification remains OPEN (SIM-C9b) |
| C-10 `split_regimes` hard-read `speed_mph` (pre-cleaned frames lost FD) (SUSPECTED) | FIXED — column fallback |

Verified clean by the reviewer: console entry points, wheel contents,
multi-seed smoke test, empty/single-sensor/DST inputs, no circular imports.

## INRIX engineer — the loader discarded every quality signal INRIX ships

| finding | disposition |
|---|---|
| X-1 `confidence_score`/`cvalue` never read: 4,948 historical-fill rows (86% speed==average_speed) ingested as measurements — the INRIX `is_observed` trap | FIXED — `min_confidence=30` default filter (pass None for legacy repro), semantics documented |
| X-2 TMC_Identification has ~6 map-version rows per tmc → unguarded merge **sextupled every reading** | FIXED — newest-version dedup per tmc |
| X-3 resample materialized every empty 5-min bin over each TMC's full span (696k readings → 18.7M bins; 34 GB run) with lone-minute bins accepted silently | FIXED — empty bins dropped, `n_minutes` support column, min_minutes guard |
| X-4 `reference_speed` ignored; vf pooled across 72 TMCs and both directions | FIXED — per-TMC vf from reference_speed when present |
| X-5 inverse-S3 synthesis at free-flow returns confident near-capacity flows (2,014 vphpl at 67 mph) | OPEN (SIM-X5) — restrict synthesis to the congested branch |
| X-6 `s3_prior_label`/`flow_synthetic` provenance dropped by schema/panel | OPEN (SIM-X6) |
| X-7 directions interleaved on one road_order axis (E+W mixed) | OPEN (SIM-X7) — partition corridors by (road, direction) |
| X-8 corridor aggregation unweighted by TMC length (0.07-mi stub = 3-mi mainline vote) | OPEN (SIM-X8) |
| X-9 `load_inrix_folder` hardcoded `Readings.csv`, failed on the repo's own benchmark | FIXED — `Reading*.csv[.gz]` glob with a helpful error |
| X-10 DATA_FORMATS mis-described the Arizona file (counts, provenance); no confidence-semantics doc | FIXED — corrected + "INRIX confidence semantics" section |

## RITIS engineer — ally-accuracy and operator trust

| finding | disposition |
|---|---|
| R-1 we under-described their ranking ("speed thresholds" — it's event clustering with head/tail tracking) | FIXED — lineage reworded: complement, not correction |
| R-2 = X-1 confidence ingestion | FIXED (above) |
| R-3 CBI score carries no user-delay / impacted-VMT currency | OPEN (SIM-R3) — delay-weighted operator view |
| R-4 red-green speed ramp unreadable for colorblind operators | FIXED — viridis ramp + numeric mph legend in the dashboard template |
| R-5 INRIX road_order labeled "MP", spillback miles from sequence deltas | OPEN (SIM-R5) — cumulative milepost from TMC lengths |
| R-6 AZ agreement page shows AM only, no per-TMC drill-down of the weak duration agreement (r=0.39) | OPEN (SIM-R6) |
| R-7 dashboards lack export/tooltips/map | OPEN (SIM-R7) |
| R-8 ranking doesn't stamp measured-vs-synthetic provenance | OPEN (SIM-X6, same fix) |
| R-9 no reliability/persistence dimension (planning-time-index style) | OPEN (SIM-R9) |
| R-10 no-endorsement caveat only in lineage doc | FIXED — mirrored on front page + cbi_arizona page |

## The structural fix both critical incidents demanded

Every dataset folder now carries a **`dataset_meta.json`** sidecar
(schema: `schemas/dataset_meta.schema.json`) declaring units and semantics
machine-readably — speed mph/kmh, flow per-lane/total, imputation flags,
confidence columns, ordering conventions, caveats. `api.read_dataset_meta`
validates it; `api.load_dataset(folder)` loads any declared dataset with
units applied from the declaration. 13 sidecars shipped. The km/h-as-mph
and per-lane-vs-total incidents can no longer recur silently on any
dataset that carries its sidecar.

## Verification after the wave

25/25 repro gates PASS · packaged smoke matrix 5/5 on wheel 2.4.0 ·
8-test regression battery over the coder findings PASS · INRIX Arizona
loader now returns a sane volume (was 112M rows / 34 GB; now bounded,
deduped, confidence-filtered).
