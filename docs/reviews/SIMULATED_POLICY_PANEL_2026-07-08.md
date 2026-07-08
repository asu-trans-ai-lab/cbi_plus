# Simulated policy panel — FHWA analyst · MPO planner · BCA economist (2026-07-08)

Wave 5 under the [AI Participant Protocol](../AI_PARTICIPANT_PROTOCOL.md):
three policy-side personas reviewed the new CBI token compiler and ranking
for **missing major policy dimensions**. Their findings converged hard —
which is itself the finding. Register rows: [../ISSUE_REGISTER.md](../ISSUE_REGISTER.md)
§8 wave 5 (POL-FIX fixed; POL-1..POL-7 open).

## The convergent verdicts

- **FHWA**: "A DOT could not cite these tokens in a federal PM3, HSIP, or
  BCA submission today… the single most important addition is a genuine
  PM3 reliability layer (LOTTR + truck TTTR)."
- **MPO**: "A genuinely strong diagnostic vocabulary… but freeway-and-
  vehicle-only, car-centric throughput metric, no equity screen — it would
  not survive a public meeting or a Title VI review unchanged."
- **BCA**: "Ship today into a BCA *appendix* as diagnostics… never
  monetize deficit area as crash or delay dollars, duration spread as
  reliability VOR, or any veh-hour figure built on synthesized volume."

## Fixed same-day (POL-FIX, v2.6.0)

| finding (who) | fix |
|---|---|
| "user time savings" label on a per-vehicle duration change invites VOT multiplication without volume (BCA CRIT, FHWA) | renamed `BENEFIT_DURATION_REDUCTION`; message says "per-vehicle diagnostic, NOT vehicle-hours" |
| `BENEFIT_SAFETY_EXPOSURE_REDUCTION` reads as monetizable crash reduction (all three) | renamed `BENEFIT_STOP_AND_GO_EXPOSURE_REDUCED`; hard caveat "crash-risk correlate, NOT a crash reduction" inline |
| `BENEFIT_RELIABILITY_GAIN` (duration std) conflated with federal reliability (all three) | renamed `BENEFIT_DURATION_STABILITY_GAIN`; caveat "not LOTTR/TTTR/buffer index" |
| duration + deficit + stability share one signal — additive monetization double-counts (BCA) | `monetization_guardrails` list on every benefit result + no-summing caveat in the message |
| fixed-demand before/after ignores induced demand (BCA, MPO) | induced-demand caveat appended to every benefit planner_message |
| heuristic cause labels asserted as causal (MPO, FHWA) | `diagnosis.attribution = "heuristic_pattern — pending incident-TIM feed"` on every token |
| planner_message not public-meeting-safe (MPO) | `public_message` variant added: cross-street-level plain language, no engineering nouns, no causal claims |
| no significance testing disclosure (MPO) | episode counts + "treat small differences as noise" in the message |

## Open policy layers (the roadmap the panel defined)

| ID | layer | why it matters | path |
|---|---|---|---|
| POL-1 | **PM3 reliability: LOTTR + TTTR** | the vocabulary federal performance processes actually ingest | computable from speed series + segment lengths over the four federal periods |
| POL-2 | person-throughput weighting | vehicle-speed severity embeds car-centric bias against transit/priority alternatives | occupancy-weighted severity + person-hours currency |
| POL-3 | EJ/Title VI overlay | "who bears the congestion" must precede any funding-priority framing | join episode locations to EJSCREEN/disadvantaged-community layers |
| POL-4 | freight: truck class, TTTR, freight VOT | freight VOT is several-fold passenger VOT; NHFP eligibility | needs classified counts |
| POL-5 | emissions/idling exposure (CMAQ hook) | stop-and-go is exactly the emissions regime | speed-bin proxy; "not conformity-grade" until an emissions model couples |
| POL-6 | honest VHD + VOT slot | the monetization base everything above needs | counted volume × lanes × length, gated to `volume_source == "measured"` |
| POL-7 | significance/CI on before-after | 5%-median thresholds flip on noise | bootstrap CI + multi-period baselines |

## What survives all three reviews unchanged

The diagnostic core: state tokens, T0–T4 markers, mismatch tokens
(`MODEL_RIGHT_AVERAGE_WRONG_SHAPE` was praised by all three), the
calibration-register loop, and the language rule ("defines the problem,
never proves the project") — the MPO persona called that discipline
"good — keep it."
