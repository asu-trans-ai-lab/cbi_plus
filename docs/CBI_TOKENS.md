# CBI_TOKENS — the planner-facing state compiler

**Design principle (2026-07-08):**

> CPI/CBI tokens turn traffic-flow diagnostics into a shared engineering
> vocabulary that an agent can detect, explain, validate, and reuse for
> calibration, scenario comparison, reliability analysis, safety-exposure
> assessment, and benefit-cost interpretation.

Shorter: **T0/T1/T2/T3 become planner-readable congestion-state tokens,
not hidden internal variables.** CBI is not only a calculation tool — it is
a *state compiler*: it translates messy traffic data into named analytical
states that humans, models, agents, dashboards, and reviewers all understand.

**Language rule (use verbatim in slides and dashboards):** a CBI token
defines the *observed operational problem* and the *calibration/benefit
target*. It never "proves the project" — only the No-Build/Build
comparison does. ("Validates the need to test the scenario," not
"validates the scenario.")

## The compiler pipeline

```
observed speed / trajectory / volume / incident data
        ↓  CBI tokenization                (cbi_pipeline/cbi_tokens.py)
planner-readable congestion states         (cbi_tokens.jsonl, cbi_event_table.csv)
        ↓  engineering diagnosis           (cause tokens, confidence)
calibration targets                        (compare_tokens → mismatch tokens)
        ↓  scenario comparison             (benefit_tokens)
cost / reliability / safety interpretation (cbi_calibration_memo.md)
```

```python
from cbi_pipeline import api
out   = api.diagnose(df)                       # out["tokens"] = observed states
mm    = api.compare_tokens(out["tokens"], out_model["tokens"])
ben   = api.benefit_tokens(nobuild["tokens"], build["tokens"])
api.write_tokens(out["tokens"], "run/cbi_tokens", mismatches=mm, benefits=ben)
```

## The state machine (evidence per transition)

```
FREE_FLOW → PRE_BREAKDOWN → CONGESTION_ONSET → QUEUE_GROWTH
      → WORST_STATE → QUEUE_DISSIPATION → RECOVERY → FREE_FLOW / RESIDUAL
```

| transition | evidence |
|---|---|
| FREE_FLOW → PRE_BREAKDOWN | speed declining but still above threshold |
| PRE_BREAKDOWN → ONSET | speed crosses the threshold (v_c) |
| ONSET → QUEUE_GROWTH | congested region persists/expands |
| QUEUE_GROWTH → WORST_STATE | minimum speed (max queue) reached |
| WORST_STATE → RECOVERY | speed improves, queue shrinks (discharge window) |
| RECOVERY → FREE_FLOW | speed above threshold, sustained |
| RECOVERY → RESIDUAL | speed above v_c but below 0.9·v_f |

## Time markers — the two-dialect map (do not mix them silently)

| memo/token dialect | meaning | pipeline internal |
|---|---|---|
| `T0_PRE_BREAKDOWN` | speeds deteriorate before formal congestion | derived (back-walk from onset) |
| `T1_ONSET` | threshold crossing | `t0_index` / `t0_time` |
| `T2_WORST_STATE` | minimum speed / max queue | `t2_index` / `t2_time` |
| `T3_RECOVERY` | return above threshold | `t3_index` / `t3_time` |
| `T4_RESIDUAL_CLEARANCE` | back within 90% of free flow | derived |
| `CONGESTION_DURATION` | T3 − T1 | `P_min` |
| `RECOVERY_DURATION` | T3 − T2 | derived |
| `SPEED_DEFICIT_AREA` | ∫ max(0, v_c − v) dt — severity, not just duration | derived (mph·h) |

Every token carries `internal_markers.dialect` so a reviewer can trace the
mapping; the same convention as the paper↔pipeline QVDF symbol map in
[GLOSSARY.md](GLOSSARY.md).

## Token families

- **A. State**: `CBI_FREE_FLOW, CBI_PRE_BREAKDOWN, CBI_CONGESTION_ONSET,
  CBI_QUEUE_GROWTH, CBI_MIN_SPEED, CBI_QUEUE_DISSIPATION, CBI_RECOVERY,
  CBI_RESIDUAL_CONGESTION, CBI_CAPACITY_DROP`
- **B. Time markers**: `T0..T4` above.
- **C. Cause diagnosis** (honest — `CAUSE_UNKNOWN` when evidence is thin):
  `CAUSE_DEMAND_SURGE, CAUSE_CAPACITY_DROP, CAUSE_INCIDENT, CAUSE_WEATHER,
  CAUSE_WORK_ZONE, CAUSE_LANE_DROP, CAUSE_RAMP_MERGE,
  CAUSE_SIGNAL_SPILLBACK, CAUSE_MANAGED_LANE_RESTRICTION, CAUSE_UNKNOWN`.
  The current compiler asserts only what episode evidence supports
  (incident-regime days, weekend surges, capacity-binding classes);
  weather/work-zone/lane-drop require external feeds (open item).
- **D. Model mismatch** (the calibration dialogue):
  `MODEL_MISSES_ONSET, MODEL_MISSES_RECOVERY, MODEL_UNDERSTATES_DURATION,
  MODEL_OVERSTATES_DURATION, MODEL_UNDERSTATES_SPEED_DROP,
  MODEL_WRONG_BOTTLENECK_LOCATION, MODEL_RIGHT_AVERAGE_WRONG_SHAPE`.
  The last one is the flagship: average travel time can look right while
  the congestion **shape** is wrong.
- **E. Scenario benefit** (planning language, deliberately non-monetized names):
  `BENEFIT_DURATION_REDUCTION, BENEFIT_DURATION_STABILITY_GAIN,
  BENEFIT_RECOVERY_IMPROVEMENT, BENEFIT_STOP_AND_GO_EXPOSURE_REDUCED,
  BENEFIT_BOTTLENECK_SHIFT, DISBENEFIT_DURATION_INCREASE`.

## Benefit translation table

| technical change | planning interpretation | monetization status |
|---|---|---|
| congestion duration (T3−T1) reduced | shorter congested period per vehicle | **diagnostic only** — NOT vehicle-hours; VHD needs counted volume × lanes × length |
| recovery time (T3−T2) reduced | improved incident resilience | qualitative |
| speed-deficit area reduced | less stop-and-go exposure | **crash-risk correlate** — never monetize as crash reduction without CMF/SPF + crash data |
| duration day-to-day spread reduced | duration-stability indicator | **not LOTTR/TTTR** — no reliability VOT without travel-time distributions |
| worst location moved | bottleneck shift — check the new location | flag, not a benefit |

**Monetization guardrails** (carried on every `benefit_tokens` result as
`monetization_guardrails`): the three duration/exposure/stability measures
share one speed-deficit signal — never sum their monetized values;
before/after holds demand fixed (induced-demand rebound unrepresented);
severity is vehicle-speed based — a person-throughput (occupancy-weighted)
view may rank transit/priority alternatives differently; no significance
testing on small samples.

## What the agent should say

Not: *"the average speed is 42 mph."* But:

> "I detected `CBI_CONGESTION_ONSET` at 06:35 near MP 5.2, followed by
> `CBI_MIN_SPEED` at 08:10. The model reproduces the average travel time
> but misses the onset by 35 minutes and recovers too early
> (`MODEL_RIGHT_AVERAGE_WRONG_SHAPE`). Review the temporal demand profile
> or the capacity-drop representation."

## Scheme integration

The AMS scheme file carries a `cbi_compiler:` block (see
[../schemas/ams_scheme_example.yml](../schemas/ams_scheme_example.yml)):
thresholds, state tokens to detect, evidence sources, observed-vs-simulated
error measures, and output artifacts (`cbi_tokens.jsonl`,
`cbi_event_table.csv`, `cbi_calibration_memo.md`).

## Verified behavior (2026-07-08)

- Simulator, 5 days: 21 tokens; SIM03 episode reads
  T0 06:35 → T1 06:40 → T2 08:55 → T3 09:55 → T4 10:30, deficit 73 mph·h,
  confidence high, cause CAUSE_CAPACITY_DROP.
- A model shifted +35 min: `MODEL_MISSES_ONSET` on 19/21 episodes,
  one `MODEL_RIGHT_AVERAGE_WRONG_SHAPE` — exactly the intended catch.
- Build scenario (peak demand 1.15→1.06): `BENEFIT_DURATION_REDUCTION`,
  `BENEFIT_STOP_AND_GO_EXPOSURE_REDUCED`, `BENEFIT_DURATION_STABILITY_GAIN`,
  with the planner message naming each dimension and its caveats.


## Policy alignment status (2026-07-08 FHWA / MPO / BCA panel)

Usable today: the tokens as *diagnostics* in a BCA appendix, TAC briefings,
and calibration registers; the `public_message` variant for public-facing
text; the ranking as *relative* prioritization (never "who gets the money"
until cost + equity attach).

Registered as open policy layers (ISSUE_REGISTER POL-1..POL-7): federal
PM3 reliability (LOTTR/TTTR percentile travel-time ratios over the federal
periods), person-throughput weighting, EJ/Title VI overlay, freight
TTTR/VOT, emissions/CMAQ hooks, measured-volume VHD + VOT slot, and
significance testing on before/after comparisons. Cause attribution is
heuristic (weekend/outlier/class patterns) pending an incident-TIM feed —
every token says so in `diagnosis.attribution`.
