# CBI+ Additional Misunderstanding Audit and HCM Community Alignment Plan

**Date:** 2026-07-08  
**Purpose:** Expand the current CBI+ issue register beyond code bugs into a sensitivity audit for misunderstanding points, adoption risks, interface gaps, document gaps, and capacity-analysis alignment needs.

## 1. Executive conclusion

The existing issue register already shows a strong engineering culture: findings are traceable from discovery source to fix and verification, with areas covering pipeline stages, public API, adapters/loaders, engines, teaching materials, website/front door, process infrastructure, simulated users, and enhancement backlog.

The next risk is not only software correctness. The next risk is **conceptual misunderstanding by users**. CBI+ must prevent users from confusing:

- observed flow with demand,
- HCM default capacity with measured discharge rate,
- V/C with dynamic congestion,
- low speed with active bottleneck,
- one-detector timing with corridor causality,
- imputed cells with field measurements,
- average weekday pattern with physical queue episode,
- FD curve fitting with valid capacity diagnosis,
- plotting dashboard with engineering decision support.

Therefore, CBI+ needs a second layer of gates: **misunderstanding gates**. These gates should be visible in the package API, CLI warnings, dashboards, reports, and teaching materials.

## 2. Why connect with the HCM / highway-capacity community

Yes, CBI+ should connect with the Highway Capacity Manual (HCM) and Highway Capacity and Quality of Service (HCQS/ACP40) community, but the message should be collaborative rather than competitive.

The positioning should be:

> HCM provides the widely accepted capacity and quality-of-service reference framework. CBI+ adds high-resolution, data-driven, queue-based, and benchmark-validated diagnosis for real corridors.

This connection is important because many agencies, consultants, and students already speak the HCM language: facility type, basic freeway segment, merge, diverge, weaving, capacity, service volume, LOS, peak-hour factor, and adjustment factors. If CBI+ does not provide an HCM crosswalk, users may not know how to interpret CBI/QVDF results in standard capacity-analysis workflows.

CBI+ should not try to replace HCM. It should provide a **dynamic companion layer**:

- HCM-style facility-type classification,
- observed-capacity and discharge-rate estimation,
- HCM-vs-observed capacity comparison,
- queue duration and D/C-hours not visible from static V/C alone,
- active/passive bottleneck diagnosis,
- benchmarked QVDF speed reconstruction,
- dynamic evidence for freeway facility analysis.

## 3. Proposed new issue category: misunderstanding gates

Add a new section to `ISSUE_REGISTER.md`:

```text
## 10. Misunderstanding gates / adoption risks
```

Suggested issue IDs below.

| ID | Severity | Misunderstanding point | User symptom | Required guard / fix |
|---|---:|---|---|---|
| MIS-1 | CRIT | Observed flow is treated as true demand during congestion | User calibrates demand from downstream collapsed flow | Add demand-source field: observed flow, upstream flow, reconstructed virtual demand, OD/model demand |
| MIS-2 | CRIT | HCM capacity, FD capacity C, and discharge rate mu are mixed | User reports one capacity number without basis | Require `capacity_basis`: HCM default, FD fit, pre-breakdown, discharge, design value |
| MIS-3 | HIGH | V/C is treated as congestion itself | User says high V/C equals bottleneck | Add report banner: V/C is stress indicator; queue diagnosis requires time-space evidence |
| MIS-4 | HIGH | Low speed is treated as active bottleneck | User ranks passive queued segments as bottlenecks | Require active/passive/spillback/artifact classification and confidence |
| MIS-5 | HIGH | Average weekday is treated as a physical queue episode | User labels average profile T0/T2/T3 as one real event | Separate `episode_day` and `average_weekday_profile` outputs and labels |
| MIS-6 | HIGH | One detector is used to infer corridor causality | User claims wave direction from one sensor | One-detector mode must say: timing only; topology/cause requires multiple detectors |
| MIS-7 | HIGH | Imputed data is treated as observed measurement | User obtains clean but false FD/QVDF fit | Prominent mask summary and gate: observed share, imputed share, duplicated profile warning |
| MIS-8 | HIGH | km/h and mph appear plausible after conversion error | User feeds IEEE/TFB km/h as mph | Units sanity gate, explicit speed_units argument, loader defaults |
| MIS-9 | MED | Per-lane and total flow are mixed | Capacity appears lanes-times too high or too low | Flow contract must declare `flow_basis=per_lane or total`; output both only after conversion |
| MIS-10 | MED | Period windows are treated as physical events | User thinks AM/PM period boundary creates queue | Docs: periods are analysis windows; episodes are data-detected events |
| MIS-11 | MED | Capacity drop is defined circularly from FD fit | mu/C looks precise but is not independent | Report uncertainty and alternative C: pre-queue peak, HCM reference, FD fit |
| MIS-12 | MED | Facility types are ignored | Merge/weave/lane drop treated like basic freeway | Add `facility_type` enum and HCM crosswalk |
| MIS-13 | MED | Managed lanes/HOV/HOT are mixed with GP lanes | Wrong capacity, speed, and queue interpretation | Add lane-group contract: GP, HOV, HOT, bus, truck, shoulder-running |
| MIS-14 | MED | Incidents and work zones are not separated from recurring bottlenecks | Event days used to calibrate recurring capacity | Add incident/work-zone flag and recurring/non-recurring separation |
| MIS-15 | MED | Dashboard figures are treated as validation | User trusts plot without pass/fail gates | Every dashboard panel must show gates, data quality, and benchmark status |
| MIS-16 | LOW | Historical benchmark comparison is missing | User cannot trace why result changed | Include benchmark_diff.csv and versioned baseline hash |
| MIS-17 | LOW | API error messages are too deep | User sees KeyError instead of contract failure | Add preflight validator and human-readable repair recipe |
| MIS-18 | LOW | Console/logging noise hides real warnings | User misses important warnings | Structured logging with severity levels and warning summary |

## 4. HCM / facility-capacity crosswalk contract

Add a new optional but strongly recommended contract:

```text
7. HCM / Facility Capacity Crosswalk Contract
```

Required fields:

| Field | Meaning | Example values |
|---|---|---|
| `facility_type` | HCM-style facility category | basic_freeway, merge, diverge, weaving, multilane_highway, ramp, managed_lane |
| `lane_group` | Operational lane class | GP, HOV, HOT, express, truck, bus, auxiliary |
| `segment_role` | Network role | upstream_approach, bottleneck, downstream_recovery, weaving_area |
| `capacity_basis` | How capacity C is defined | hcm_default, field_pre_breakdown, fd_fit, discharge_mu, design_assumption |
| `capacity_vphpl` | Capacity per lane | numeric |
| `capacity_total_vph` | Segment total capacity | numeric |
| `discharge_mu_vphpl` | Observed discharge rate per lane | numeric |
| `mu_over_C` | Discharge/capacity ratio | numeric |
| `free_flow_speed_mph` | FFS or reference speed | numeric |
| `analysis_period` | HCM/CBI period label | AM, MD, PM, MDPM, custom |
| `resolution_minutes` | Data resolution | 5, 15, 60 |
| `hcm_compatible_summary` | Whether the output can be compared with HCM-style analysis | true/false + limitations |

## 5. Suggested package features

### 5.1 Preflight report

Before running FD, CBI, or QVDF, the package should produce:

```text
cbi.preflight(df, corridor_manifest)
```

Expected output:

- unit checks,
- missing columns,
- observed/imputed summary,
- speed/flow/density plausibility,
- per-lane vs total-flow check,
- facility-type completeness,
- detector ordering check,
- time-zone and time-resolution check,
- whether data supports single-detector timing or corridor causality.

### 5.2 HCM crosswalk summary

Add:

```text
cbi.hcm_crosswalk(results)
```

Output columns:

- facility type,
- lane group,
- HCM reference capacity if supplied,
- observed pre-breakdown capacity,
- observed discharge rate,
- mu/C,
- dynamic queue duration,
- D/C-hours,
- QVDF speed MAE,
- HCM-compatible interpretation note.

### 5.3 Dashboard warning cards

Every dashboard should have three visible cards:

1. **Can I run?** data contract and unit validity.
2. **Can I trust it?** quality, observed share, physics gates, benchmark status.
3. **Can I use it for decisions?** facility type, bottleneck diagnosis, uncertainty, recommended interpretation.

## 6. Recommended documentation additions

Create short documents, each no more than 2-4 pages:

1. `docs/MISUNDERSTANDING_GATES.md`
2. `docs/HCM_CROSSWALK.md`
3. `docs/CAPACITY_DEFINITIONS.md`
4. `docs/OBSERVED_FLOW_IS_NOT_DEMAND.md`
5. `docs/ACTIVE_VS_PASSIVE_BOTTLENECK.md`
6. `docs/AVERAGE_WEEKDAY_VS_EPISODE.md`
7. `docs/FACILITY_TYPE_AND_LANE_GROUPS.md`
8. `docs/DASHBOARD_INTERPRETATION_GUIDE.md`

## 7. HCM community engagement plan

### Phase 1: Internal crosswalk

Prepare a one-page comparison:

| HCM language | CBI+ dynamic extension |
|---|---|
| facility type | detector/link/lane-group/facility manifest |
| capacity | observed C, discharge mu, uncertainty |
| PHF | 5-min/15-min dynamics and queue duration |
| V/C | D/C-hours and queue-based congestion pressure |
| LOS / speed | QVDF reconstructed speed profile and benchmark error |
| freeway segment | active/passive bottleneck and spillback diagnosis |

### Phase 2: Friendly review

Ask HCM/HCQS-oriented colleagues to review:

- capacity definitions,
- facility-type labels,
- HCM-compatible summary tables,
- whether CBI+ outputs can be useful as empirical calibration inputs for HCM-style freeway analysis.

### Phase 3: Joint use case

Prepare one freeway case study:

- one basic freeway segment,
- one merge/diverge/weaving bottleneck,
- one managed-lane or HOV/GP comparison,
- HCM-style summary plus CBI+ dynamic diagnosis.

### Phase 4: TRB / workshop positioning

Position the tool as:

> A dynamic, data-driven companion to capacity and quality-of-service analysis, designed to help students and practitioners connect HCM concepts with high-resolution detector/probe data, queue dynamics, QVDF calibration, and benchmark validation.

## 8. Top priority actions for the development team

1. Add `docs/MISUNDERSTANDING_GATES.md`.
2. Add `docs/HCM_CROSSWALK.md`.
3. Add `capacity_basis` and `facility_type` to the corridor manifest.
4. Add `flow_basis` and `speed_units` as required inputs or safe defaults in loaders.
5. Add preflight warnings for demand/flow, units, imputed data, detector ordering, and one-detector limitations.
6. Add HCM-compatible output table.
7. Add dashboard cards for run/trust/decision readiness.
8. Add regression tests for each misunderstanding gate.
9. Add a public-friendly statement: "CBI+ complements HCM; it does not replace it."
10. Add one benchmark case showing HCM-style static summary vs CBI+ dynamic diagnosis.

## 9. One-sentence framing

**CBI+ should become the bridge between HCM-style capacity analysis and high-resolution, mechanism-based congestion diagnosis: not a replacement for HCM, but a dynamic evidence layer that helps users understand where capacity, demand, queues, and bottlenecks actually come from.**
