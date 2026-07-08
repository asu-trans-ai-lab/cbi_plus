# ISSUE_REGISTER — every bug, issue, and enhancement, traceable

One register, per tool area, so any issue can be traced from *discovery
source* → *fix* → *verification*. This is Contract-style Principle 4 in
action: findings become register rows, not emails.

**How to read status:** `FIXED` (with commit/doc trace) · `DOCUMENTED`
(known limitation, by design) · `OPEN` (backlog) · `WONTFIX` (with reason).

**How to file:** add a row with the next ID in the right area, link the
source (review doc, ticket, gate failure), and never delete rows — flip
status instead. The operating standard for simulated-participant waves is
[AI_PARTICIPANT_PROTOCOL.md](AI_PARTICIPANT_PROTOCOL.md); live run/issue
logs: [reviews/ai_participant_run_log.csv](reviews/ai_participant_run_log.csv),
[reviews/ai_participant_issue_log.csv](reviews/ai_participant_issue_log.csv).

---

## 1. Pipeline stages (cbi_pipeline stage 0–6)

Full narratives with evidence in [FIXES_CBI_PLUS_2026-07-07.md](FIXES_CBI_PLUS_2026-07-07.md).

| ID | sev | title | source | status |
|---|---|---|---|---|
| PIPE-1 | ★CRIT | period-relative indices applied to full-day frames (μ read at midnight) | external results review F1-family | FIXED — PERIOD_SLICE_BOUNDS + period_hour_mask in schemas.py; applied in stages 4/5/2b |
| PIPE-2 | HIGH | OSM/GMNS lane tags unreliable → per-lane flows wrong (lanes=2 on 5,136 veh/h) | results review | FIXED — effective lanes = clip(round(p99 flow/2000),2,6) in adapters |
| PIPE-3 | MED | episode detector: silent fallback + fragile scan (NaN gaps, 1-bin blips) | results review | FIXED — NaN-gap guard ≥3 bins + 2-bin persistence |
| PIPE-4 | MED | event z-score pooled AM/MD/PM baselines | results review | FIXED — per (sensor_uid, period) |
| PIPE-5 | MED | direction gate assumed ONE bottleneck over the whole window (0.375 FAIL on healthy corridor) | results review | FIXED — per-day, segment-aware multi-bottleneck check + forward-wave slope guard (→0.90 PASS) |
| PIPE-6 | HIGH | MD→PM boundary queues truncated; MD "discharge" was mid-queue | results review | FIXED — MDPM boundary-merge pass |
| PIPE-7 | HIGH | stage2b computed a DIFFERENT μ (full-day indices again) | results review | FIXED — one canonical μ implementation |
| PIPE-8 | HIGH | stage5 D/C units (÷P_hours ÷lanes double-count) → duration model NaN in 100% of rows | results review F1 | FIXED — D/C in HOURS convention, everywhere |
| PIPE-9 | LOW | verification panels covered only MD | results review | FIXED |
| PIPE-10 | HIGH | imputed benchmark data ingested as measured (duplicate FD fits, 9,443 vphpl capacities) | results review | FIXED — adapters blank is_observed=False, drop stations <60% observed |
| PIPE-11 | MED | itertuples strips dunder columns (`__pos__`) | dev-time crash | FIXED — renamed `pos_` |
| PIPE-12 | LOW | period-edge truncation at 10:00/20:00 | results review | DOCUMENTED — known limitation |

## 2. Package / public API (pip cbi-plus)

| ID | sev | title | source | status |
|---|---|---|---|---|
| PKG-1 | HIGH | `np.trapz` removed in NumPy 2.x; compat shim's fallback was evaluated **eagerly** (`getattr(np,"trapezoid", getattr(np,"trapz"))` raises on 2.4) | clean-venv install matrix 2026-07-08 | FIXED — lazy fallback in stage5_qvdf.fit_shape_model |
| PKG-2 | HIGH | six modules called `matplotlib.use("Agg")` at import time, silently killing notebook plotting; on ipykernel 7 the inline backend is literally named `"inline"` | notebook execution 2026-07-08 | FIXED — guarded use() respecting inline/nbagg/ipympl in all 6 modules |
| PKG-3 | MED | FD model names case-sensitive (`"s3"` → KeyError) | packaged smoke matrix | OPEN — accept case-insensitive lookup + helpful error listing models |
| PKG-4 | MED | `fit_fd_huber` returns raw params without derived capacity/v_c; every caller re-derives the curve peak | packaged smoke matrix | OPEN — add derived `capacity_vphpl`/`k_c`/`v_c` to the fit dict |
| PKG-5 | LOW | `run_ranking` requires an out_dir (side effect); `api.diagnose` hides it behind a temp dir | api design pass | OPEN — pure in-memory mode for run_ranking |
| PKG-6 | LOW | episode validity flag named `is_valid_for_mu` (easy to guess `is_valid` and crash) | api dev 2026-07-08 | OPEN — alias column or document prominently |
| ENV-1 | MED | Windows MAX_PATH: pip install fails in deep venv paths (sklearn test files) | clean-venv install | DOCUMENTED — use short venv path; consider long-path note in PACKAGE_GUIDE |

## 3. Adapters / loaders (PeMS, INRIX, TFB, IEEE v4)

| ID | sev | title | source | status |
|---|---|---|---|---|
| ADPT-1 | HIGH | TFB/IEEE releases carry imputed cells (`is_observed=0`) that look like measurements | TFB integration | FIXED in adapters; **OPEN** for raw `api.diagnose` users — no warning if you feed imputed rows yourself |
| ADPT-2 | HIGH | IEEE v4 speeds are km/h; nothing stops a user feeding them as mph (silently plausible garbage) | packaged smoke matrix | OPEN — units sanity check + `from_ieee_v4()` convenience loader |
| ADPT-3 | MED | INRIX qc_pass_rate tuning on I-395 NVTA path | NVTA run | OPEN |
| ADPT-4 | LOW | `--corridor 5-N` README example fell back to a nonexistent data path | student read-through | FIXED — quickstart runs from a clone |

## 4. Engines & arenas

| ID | sev | title | source | status |
|---|---|---|---|---|
| ENG-1 | MED | PAQ shape fits gave negative R² when fit over the full window | PAQ reproduction | FIXED — fit on the queue's zero-to-zero span; trapezoid added to family |
| ENG-2 | LOW | legacy Jayakrishnan FD bug preserved intentionally for exact reproduction | fd_16models repro | DOCUMENTED |
| ENG-3 | MED | AI-arena winners flip with masking geometry (cells vs blocks) | ai_arena runs | DOCUMENTED on dashboards — always state masking mode |

## 5. Teaching materials (notebooks, Excel, guides)

| ID | sev | title | source | status |
|---|---|---|---|---|
| NB-1 | HIGH | notebooks executed headless captured zero plots (PKG-2 root cause) | notebook build | FIXED — backend guard + `%matplotlib inline` |
| DOC-1..10 | mixed | ten broken onboarding trails (paths, missing hello-world, TFB gating, quiz set) | [student read-through](reviews/STUDENT_READTHROUGH_2026-07-08.md) | FIXED — all top-10 applied 2026-07-08 |

## 6. Website / front door

| ID | sev | title | source | status |
|---|---|---|---|---|
| WEB-1 | HIGH | GitHub landing showed no figure (README, not index.html, renders there) | user report 2026-07-08 | FIXED — hero figure + KPI strip + front doors in README |
| WEB-2 | — | simulated multi-university panel findings (MIT / UC Berkeley / ASU novice / CS-AI / TU Delft) | this register, §8 | see appended rows |

## 7. Process / infrastructure

| ID | sev | title | source | status |
|---|---|---|---|---|
| PROC-1 | ★CRIT | piped validator (`validate … \| tail -1 && git push`) tested the wrong exit code → failing check bypassed, 335 legacy files pushed | ship incident | FIXED forward (untracked + ignored); **OPEN**: history purge awaits approved force-push (`release_v1` branch ready) |
| PROC-2 | MED | INTELLECTUAL_LINEAGE carried a named team table unsuitable for public release | publish-precondition review | FIXED — de-named 37ef6bb; names in untracked INTERNAL_TEAM_ROLES.md |
| PROC-3 | LOW | PyPI upload pending (owner token) | PACKAGE_GUIDE | OPEN — owner action |

## 8. Simulated-user findings (2026-07-08 wave)

Appended after each simulation wave; full reports in
[reviews/SIMULATED_PANEL_2026-07-08.md](reviews/SIMULATED_PANEL_2026-07-08.md)
and [reviews/SIMULATED_COMPETITION_USERS_2026-07-08.md](reviews/SIMULATED_COMPETITION_USERS_2026-07-08.md).

**Competition-user tickets (all triaged; details + journeys in the reports):**

| ID | sev | title | status |
|---|---|---|---|
| SIM-T1 | ★CRIT | flow-units contract self-contradiction (per-lane vs total) — capacities silently ~lanes× off | FIXED v2.3.0 — per-lane everywhere + magnitude warning |
| SIM-M1 | ★CRIT | km/h fed as mph → silent garbage (QC pass 0.908→0.079, plausible wrong ranking) | FIXED v2.3.0 — median>90 warning + `speed_units="kmh"` + loader |
| SIM-T2 | HIGH | FD failures swallowed; `density_vpm` required but undocumented | FIXED v2.3.0 — auto-derived k=q/v + loud warnings + doc row |
| SIM-M3 | HIGH | `run_qvdf` KeyError on short windows (empty params frame lost schema) | FIXED v2.3.0 |
| SIM-M4 | HIGH | impossible FD fits returned unflagged (14,295 vphpl, negative R²) | FIXED v2.3.0 — `fit_ok` physics gate |
| SIM-T4 | HIGH | no IEEE v4 loader in the wheel | FIXED v2.3.0 — `api.load_ieee_v4` (also fixes southbound ordering + data-derived lanes) |
| SIM-M5 | MED | "recommended" columns hard-required via deep KeyErrors | FIXED v2.3.0 — upfront validator + defaults |
| SIM-M7 | MED | tz-aware timestamps silently accepted (period labels would shift 7–8 h) | FIXED v2.3.0 — rejected with recipe |
| SIM-M8 | MED | outputs use bin indices with undocumented frame | FIXED v2.3.0 — `t*_time` clock columns + schema table |
| SIM-T7 | MED | scare-print "fallback … not found" on clean installs | FIXED v2.3.0 |
| SIM-M9 | LOW | `__version__` 0.1.0 vs pip 2.2.0 | FIXED v2.3.0 — single-sourced |
| SIM-T10 | LOW | Windows cp1252 mojibake in console prints | PARTIAL — worst message fixed; full logging sweep open (SIM-P7) |

**Panel findings (dispositions in SIMULATED_PANEL report; open ones below):**

| ID | sev | title | status |
|---|---|---|---|
| SIM-NB1 | HIGH | NB01 prose vs table contradiction (seed-dependent ranking) | FIXED v2.3.0 — simulator physics rewrite; SIM03 #1 across 10 seeds |
| SIM-B1 | HIGH | simulator physics: no discharge phase (T2==T3), flat flow, conservation violation downstream, hard tail cutoff | FIXED v2.3.0 — queue-balance rewrite; NB02 measures μ/C=0.920 |
| SIM-P1 | MED | single-detector T0/T2/T3 labeling language overstates what one sensor supports | OPEN — docs pass: timing vs topology claims |
| SIM-P2 | MED | μ/C near-circularity; drop defined vs FD-fit C not pre-breakdown peak | OPEN — methodological (report C's CI or pre-queue peak) |
| SIM-P3 | MED | AI-arena: PINN registered but never run; single-seed MAEs; tensor prose numbers lack backing tables | OPEN — seed-sweep rerun + honest PINN status |
| SIM-P4 | MED | flow_tensor price-of-rank partly evaluated on imputed cells | OPEN — held-out-mask evaluation |
| SIM-P5 | MED | synthesized-volume feeds can yield zero valid discharge windows (Δq guard on smooth recovery) | OPEN — relax guard when flow_synthetic=True |
| SIM-P6 | LOW | duration-outlier days asserted as "events"/incidents | OPEN — rename or corroborate |
| SIM-P7 | LOW | print-based stage chatter; non-ASCII console breakage | OPEN — logging migration |
| SIM-P8 | LOW | no CI matrix / tests package in wheel | OPEN — infra |

**Wave 3 (RITIS engineer / INRIX engineer / staff coder — full report:
[reviews/SIMULATED_INDUSTRY_CODER_2026-07-08.md](reviews/SIMULATED_INDUSTRY_CODER_2026-07-08.md)):**

| ID | sev | title | status |
|---|---|---|---|
| SIM-C1 | ★CRIT | `diagnose` never passed road_order to ranking — bottleneck classes on ALPHABETICAL sensor order | FIXED v2.4.0 |
| SIM-X2 | ★CRIT | INRIX TMC map-version rows sextupled every reading on merge | FIXED v2.4.0 |
| SIM-X3 | ★CRIT | INRIX resample densified empty bins (696k readings → 112M rows / 34 GB) | FIXED v2.4.0 |
| SIM-X1 | HIGH | confidence_score/cvalue never read — historical fill ingested as measurement | FIXED v2.4.0 — min_confidence=30 default |
| SIM-C2 | HIGH | speed-only frames crashed the panel (`KeyError flow_vph`) | FIXED v2.4.0 |
| SIM-C3 | HIGH | `t*_time` drifted across data gaps (positional-index arithmetic) | FIXED v2.4.0 |
| SIM-C4..C6 | MED | degenerate-sensor FD wipeout; kmh skipped on pre-cleaned; v4 id-mismatch silent -1 | FIXED v2.4.0 |
| SIM-X4 | MED | vf pooled across TMCs/directions instead of reference_speed | FIXED v2.4.0 |
| SIM-X9 | LOW | load_inrix_folder failed on the repo's own benchmark filename | FIXED v2.4.0 |
| SIM-R1/R4/R10 | HIGH/MED | RITIS mischaracterization; colorblind ramp; missing no-endorsement caveats | FIXED v2.4.0 |
| SIM-META | — | **dataset_meta.json standard**: per-dataset units/semantics sidecar (13 shipped) + `api.load_dataset` / `read_dataset_meta` + JSON Schema — structural fix for SIM-M1/SIM-T1 | SHIPPED v2.4.0 |
| SIM-X5 | MED | inverse-S3 synthesis ill-posed at free flow (confident near-capacity flows) | OPEN |
| SIM-X6 | MED | flow_synthetic / s3_prior_label provenance dropped by schema + panel; ranking lacks measured-vs-synthetic stamp (=R-8) | OPEN |
| SIM-X7 | MED | INRIX directions interleave on one road_order axis | OPEN |
| SIM-X8 | MED | corridor aggregation not length-weighted | OPEN |
| SIM-R3 | MED | no delay/impacted-VMT currency in the operator ranking | OPEN |
| SIM-R5 | MED | INRIX road_order labeled "MP"; spillback miles from sequence deltas | OPEN |
| SIM-R6/R7/R9 | MED/LOW | AZ agreement drill-down; dashboard export/tooltips/map; reliability dimension | OPEN |
| SIM-C8 | LOW | external Part1 detector import reachable from the wheel's sys.path | OPEN |
| SIM-C9b | LOW | bootstrap capacity grid differs from fit_fd_huber's | OPEN |

## 9. Enhancement backlog (not bugs — wanted capabilities)

| ID | title | driver |
|---|---|---|
| ENH-1 | adoption gap 3: per-episode queue_length + wave_direction columns | positioning memo (ADOPTION_TRACE) |
| ENH-2 | adoption gap 4: facility-type / merge-diverge ingestion | ADOPTION_TRACE |
| ENH-3 | adoption gap 5: detector_status enum | ADOPTION_TRACE |
| ENH-4 | `from_ieee_v4()` / `from_tfb()` one-line loaders with unit + mask handling | competition simulations |
| ENH-5 | units sanity guard in run_qc (median speed > 90 → "did you feed km/h?") | ML-team simulation |
| ENH-6 | CITATION.cff + LICENSE file + version/changelog surfaced on the front page | Delft-persona review |
| ENH-7 | type hints + py.typed marker in the wheel | CS-persona review |
| ENH-8 | NVTA / TFB corridor backlog runs | corridor roadmap |


## 10. Misunderstanding gates / adoption risks

Source: `cbi_plus_additional_misunderstanding_audit.md` (2026-07-08) — extends the register
from software bugs to CONCEPTUAL MISUSE risks. Student edition: `MISUNDERSTANDING_GATES.md`.
Positioning: CBI+ complements HCM; it does not replace it.

| ID | Sev | Misunderstanding | Required guard | Status |
|---|---|---|---|---|
| MIS-1 | CRIT | observed flow treated as true demand | required `demand_source` field | open |
| MIS-2 | CRIT | HCM capacity / FD C / discharge mu mixed | required `capacity_basis` field | open |
| MIS-3 | HIGH | V/C treated as congestion | V/C warning banner in reports | open |
| MIS-4 | HIGH | low speed treated as active bottleneck | active/passive/spillback/artifact label + confidence | open |
| MIS-5 | HIGH | average weekday treated as physical episode | separate episode_day vs average_weekday_profile outputs | open |
| MIS-6 | HIGH | one detector used for corridor causality | one-detector mode: timing only | open |
| MIS-7 | HIGH | imputed data treated as measurement | observed/imputed share gate + duplicate-profile warning | open |
| MIS-8 | HIGH | km/h fed as mph | unit sanity gate + explicit speed_units in loaders | open |
| MIS-9 | MED | per-lane vs total flow mixed | required `flow_basis` field | open |
| MIS-10 | MED | period windows treated as physical events | docs: periods = analysis windows, episodes = detected events | open |
| MIS-11 | MED | capacity drop defined circularly from FD fit | report uncertainty + alternative C bases | open |
| MIS-12 | MED | facility type ignored (merge/weave as basic) | `facility_type` enum + HCM crosswalk contract (contract 7) | open |
| MIS-13 | MED | managed/HOV/HOT mixed with GP lanes | lane-group contract | open |
| MIS-14 | MED | incidents/work zones mixed into recurring calibration | incident/work-zone flag + recurring/non-recurring split | open |
| MIS-15 | MED | dashboard figures treated as validation | every panel shows gates + data quality + benchmark status | open |
| MIS-16 | LOW | no historical benchmark comparison | benchmark_diff.csv + versioned baseline hash | open |
| MIS-17 | LOW | raw KeyError instead of contract failure | preflight validator + repair recipe | open |
| MIS-18 | LOW | log noise hides real warnings | structured logging + warning summary | open |

New contract to add: **7. HCM / Facility Capacity Crosswalk** (facility_type, lane_group,
segment_role, capacity_basis, capacity_vphpl, capacity_total_vph, discharge_mu_vphpl,
mu_over_C, free_flow_speed_mph, analysis_period, resolution_minutes, hcm_compatible_summary).
Package features queued: cbi.preflight(), cbi.hcm_crosswalk(), dashboard run/trust/decision cards.
