# Misunderstanding Gates — what CBI+ will NOT let you get wrong (student edition)

*CBI+ complements the Highway Capacity Manual; it does not replace it. HCM gives the standard
capacity and quality-of-service language; CBI+ adds high-resolution, queue-based, benchmark-
validated dynamic evidence.* This page teaches the ten conceptual traps that ruin real corridor
studies — each has a guard in the software, but the guard only helps if you understand WHY.
Full audit: `cbi_plus_additional_misunderstanding_audit.md` · register: ISSUE_REGISTER.md §10.

## The ten highest-risk misunderstandings

| ID | The misunderstanding | Why it is dangerous | The guard (and the field you must fill) |
|---|---|---|---|
| **MIS-1** | **Observed flow = true demand** | During congestion, a detector measures what got THROUGH, not what wanted to come — downstream collapsed flow hides suppressed demand. Calibrating demand from it bakes the queue into your "demand." | required `demand_source`: observed_flow / upstream_flow / reconstructed_virtual_demand / od_model |
| **MIS-2** | **HCM capacity = FD capacity = discharge μ** | Three different numbers with three different definitions get reported as one "capacity." Your μ/C ratio becomes meaningless. | required `capacity_basis`: hcm_default / field_pre_breakdown / fd_fit / discharge_mu / design_assumption |
| **MIS-3** | **V/C = congestion** | V/C is a *static stress indicator*. A segment at V/C 0.95 may flow freely; one at 0.7 may sit in a spillback queue. Diagnosis needs time-space evidence. | V/C warning banner on every report: "stress indicator — queue diagnosis requires time-space evidence" |
| **MIS-4** | **Low speed = active bottleneck** | Most slow segments are PASSIVE — they sit inside someone else's queue. Ranking them as bottlenecks sends the fix to the wrong milepost. | required label: active / passive / spillback / artifact + confidence |
| **MIS-5** | **Average weekday = a physical episode** | An average profile is a synthetic object; its "T0/T2/T3" never happened on any real day. Treating it as one event fabricates a queue story. | separate outputs + labels: `episode_day` vs `average_weekday_profile` |
| **MIS-6** | **One detector proves causality** | Wave direction (did the queue come from downstream?) cannot be inferred from a single point. One detector gives timing only. | one-detector mode prints: "timing only — topology/causality requires multiple detectors" |
| **MIS-7** | **Imputed data = measurement** | Imputation produces beautiful, self-consistent, WRONG fundamental diagrams and QVDF fits. | observed/imputed share gate + duplicated-profile warning, shown before any fit |
| **MIS-8** | **km/h read as mph** | A 100 km/h freeway "at 100 mph" still looks plausible — every ranking downstream is silently wrong. | unit sanity gate + explicit `speed_units` in every loader |
| **MIS-9** | **Per-lane vs total flow mixed** | Capacity off by exactly the lane count — the most common silent factor error in capacity work. | required `flow_basis`: per_lane / total; both emitted only after explicit conversion |
| **MIS-12** | **Facility type ignored** | A merge, weave, or lane-drop analyzed as a basic freeway segment misestimates capacity by construction. | required `facility_type` (HCM enum) + the HCM/facility crosswalk contract |

## How to use this page (students)

1. Before running anything: `cbi.preflight(df, corridor_manifest)` — it checks units, imputed
   share, per-lane/total, detector ordering, and whether your data can even answer your question.
2. For every number you report, be able to answer: *which basis?* (MIS-2, MIS-9), *observed or
   imputed?* (MIS-7), *active or passive?* (MIS-4), *episode or average?* (MIS-5).
3. The dashboard's three cards are your checklist: **Can I run? · Can I trust it? · Can I use
   it for decisions?** A plot is not validation (MIS-15 in the full register).

## Self-test (answer before touching real data)

1. Your detector shows 1,650 veh/h/ln during the peak. Is corridor demand 1,650? (MIS-1)
2. Your FD fit says C = 2,210; HCM says 2,400; discharge after breakdown is 1,980. Which do
   you report, and under what name? (MIS-2)
3. MP 12.4 averages 23 mph between 4–6 PM. Is MP 12.4 a bottleneck? (MIS-4, MIS-6)
4. Your average-weekday heatmap shows a clean queue 15:40–18:05. When did that queue occur? (MIS-5)

*(Answers: 1 — no; that is throughput, demand needs a declared source. 2 — all three, each with
its `capacity_basis`. 3 — unknown; needs active/passive classification and neighbors. 4 — never;
it is a synthetic profile.)*
