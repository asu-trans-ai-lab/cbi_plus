# Simulated IEEE BigData competition participants — 2026-07-08

Two persona agents actually **ran the installed cbi-plus wheel** (v2.2.0 in
a clean venv) against the IEEE v4 sample corridors, as competition
participants would: learning from docs only, adapting data themselves,
filing a ticket for every friction point. This file records their journeys,
every ticket, and the disposition. Master traceability:
[../ISSUE_REGISTER.md](../ISSUE_REGISTER.md) §8.

- **Team FlowState** — two traffic-engineering MS students. Applied the
  pipeline to I-405S (southbound!), cross-checked their own S3 fits against
  the shipped chain reference on I-5N, produced a competition-style
  bottleneck-ranking CSV. Filed 11 tickets (T-1..T-11).
- **Team GradientDescent** — solo ML engineer, zero traffic background.
  Copy-pasted quick starts, extracted queue features for an ML matrix, and
  deliberately fed km/h data as mph to test for silent failure. Filed 9
  tickets (M-1..M-9).

## Their headline numbers (real runs)

- I-405S: 68 detectors × 3 days (58,752 rows) diagnosed in **6.8 s** → 620
  episodes, 13 ranked sensor-periods (top: P=4.83 h, v_t2=23.8 mph).
- I-405N: 634 episodes / 27 ranked in 2.6 s — matching the reference run.
- Independent S3 capacity fits on I-5N landed 13–18% below the shipped
  chain reference on congested detectors (consistent with 3-day
  undersampling + discharge-regime data) — and **21% above** on an
  uncongested detector with R²=0.994: a textbook identifiability failure
  the package did not flag (now it does — `fit_ok`).
- The km/h-as-mph poisoning test: QC pass rate silently collapsed 0.908 →
  **0.079** yet still emitted a plausible ranking (v_t2 14.3 vs true 8.9
  mph) — the single most dangerous behavior found all day (now warned).

## Tickets → disposition (same-day fixes in v2.3.0)

| ticket | severity | disposition |
|---|---|---|
| T-1 flow-units contract contradicts itself (schemas: per-lane; guide: total; notebook: total) — capacities silently ~lanes× off | CRITICAL | **FIXED**: per-lane is the contract everywhere; guide + notebook corrected; simulator emits per-lane; p95>3200 warning in `diagnose` |
| M-1 km/h in `speed_mph` → silent garbage | CRITICAL | **FIXED**: median>90 loud warning + `speed_units="kmh"` parameter + `load_ieee_v4` converts |
| T-2/M-2 FD failures swallowed; `density_vpm` required but undocumented | HIGH | **FIXED**: density auto-derived (k=q/v) when absent; failures warn loudly; column documented |
| M-3 `diagnose`→`run_qvdf` contract break on short windows (empty params frame lost its schema) | HIGH | **FIXED**: empty fit frame keeps schema; 3-day samples return honest `n_fitted=0` |
| M-4 physically impossible FD fits returned unflagged (capacity 14,295 vphpl, negative R²) | HIGH | **FIXED**: `fd_summary["fit_ok"]` physics gate + warning |
| T-4/M-6 no IEEE v4 loader in the wheel (~35 lines of boilerplate each team) | HIGH | **FIXED**: `api.load_ieee_v4(states_csv, chain_csv=None)` — km/h→mph, total→per-lane via data-derived effective lanes, `is_observed` filter, chain ordering |
| T-5 notebook 05's "one line" swap wrong for southbound (milepost reversal), hardcoded lanes, .gz | MED | **FIXED**: notebook uses the loader; south/westbound + .gz notes added. Note: the chain's own lane tags proved unreliable (lanes=1 on a 12,000 veh/h station) — loader derives effective lanes from data (the PIPE-2 lesson, re-learned) |
| M-5 "recommended" columns actually hard-required, KeyErrors deep in pandas | MED | **FIXED**: one upfront validator lists ALL missing required columns; recommended columns get defaults |
| M-7 tz-aware timestamps accepted silently (would shift every AM/PM label) | MED | **FIXED**: rejected with a conversion recipe |
| M-8 output names ≠ README symbols; bin indices undocumented | MED | **FIXED**: `t0_time/t2_time/t3_time` clock columns added; name map in `diagnose` docstring + return-schema table in PACKAGE_GUIDE |
| T-6 `fd_model_zoo` documented as a call; registry hidden | MED | **FIXED**: `api.fd_models()`; case-insensitive `fit_fd_huber` with helpful error; guide row corrected |
| T-7 "fallback … not found" scare-print on every clean install | MED | **FIXED**: reworded ("packaged detector") |
| M-9 version mismatch (`pip show` 2.2.0 vs `__version__` 0.1.0) | LOW | **FIXED**: single-sourced from package metadata |
| T-9 no identifiability guard (uncongested detector → confident nonsense capacity) | LOW | **FIXED** via `fit_ok` band + `identified`-style k-range logic in fit derivation |
| T-8 return schemas undocumented | LOW | **FIXED**: schema table in PACKAGE_GUIDE |
| T-11 samples contain 0% imputed cells — can't rehearse the pitfall | LOW | **FIXED**: stated in ieee_v4_samples README |
| T-10/M-9b Windows cp1252 mojibake in console prints | LOW | PARTIAL: worst message fixed; full ASCII/logging sweep is SIM-P7 (open) |
| T-3 `density_vpm` doc row | HIGH | **FIXED** (with T-2) |

## Their verdicts

- FlowState: "a real team can use this — 68 detectors × 3 days in 7 s and
  our independent fits landed within 13–18% of the shipped references —
  but the ingestion layer is where all our time went. One shipped
  `load_ieee_v4` loader would have eliminated tickets T-1 through T-5."
  → shipped in v2.3.0.
- GradientDescent: "nothing else in my stack produces 'when did the queue
  start' as a mergeable column… but I only trust it because I accidentally
  ran the units test. A loud input validator + loader doubles adoption."
  → both shipped in v2.3.0.
