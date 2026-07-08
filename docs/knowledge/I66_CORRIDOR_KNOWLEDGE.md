# I-66 corridor knowledge — RAG run 2026-07-08

First Evidence-Compiler run on the I-66 corridor (Northern Virginia),
gathering what AMS modeling needs before any simulation: network context,
demand signals, known bottlenecks, and the natural experiment the corridor
offers. Machine-readable outputs: issues in
[i66_issue_graph.json](i66_issue_graph.json); sources appended to
[source_registry.json](source_registry.json). **No I-66 detector/probe
data is in-repo yet — every bottleneck and reliability claim below is
text-derived, capped, and flagged `needs_detector_check`.** That flag IS
the first work item.

## Network context (what the model must represent)

- **Outside the Beltway (OTB)**: 22.5 mi of express lanes (2 EL + 3 GP per
  direction) from I-495 to US-29 Gainesville; phased opening fall 2022
  (Gainesville–Rt 28 in Sept, Rt 28–I-495 in Nov)
  ([VDOT Transform 66 Outside](https://www.vdot.virginia.gov/projects/major-projects/transform66/transform66-outside/),
  [FHWA project profile](https://www.fhwa.dot.gov/ipd/project_profiles/va_transform_66.aspx)).
  Concession-operated ([Ferrovial / I-66 EMP](https://www.ferrovial.com/en/business/projects/i66-highway/)).
- **Inside the Beltway (ITB)**: all lanes peak-direction HOT since Dec
  2018 (EB 5:30–9:30a, WB PM), dynamic tolls updated every 6 minutes;
  HOV-2+ exempt
  ([VDOT Transform 66 Inside](https://www.vdot.virginia.gov/projects/major-projects/transform66/transform66-inside/),
  [peer-reviewed ITB tolling study](https://www.sciencedirect.com/science/article/pii/S2666691X21000154)).
- Interchange rebuilds change topology mid-history: Nutley St double
  roundabout (opened ~Feb 2023)
  ([VDOT NoVA](https://www.vdot.virginia.gov/news-events/news/northern-virginia-district/i-66nutley-street-roundabouts-to-open-on-or-about-feb-28.html)) —
  GMNS network must be **era-stamped** (pre/post 2022-11 OTB opening;
  pre/post 2023-02 Nutley).

## Candidate bottlenecks (text-derived — detectors must confirm)

| location | text evidence | status |
|---|---|---|
| Nutley St interchange (Vienna Metro) | "overburdened", extreme merge pressure; rebuilt 2023 | needs_detector_check |
| Route 28 merge (Centreville) | recurring congestion location, years-long | needs_detector_check |
| Eastern corridor approaching I-495 | 2013 pre-project study: 4–5 h congestion each direction, projected 8–10 h Nutley↔Beltway ([WaPo](https://www.washingtonpost.com/local/trafficandcommuting/i-66-study-shows-difficult-road-ahead-for-northern-virginia-commuters/2013/03/30/c5feaec0-933b-11e2-8ea1-956c94b6b5b9_story.story.html)) | pre-project context only |

## Demand signals (for the demand side of the AMS scheme)

- **The toll profile is a live demand-intensity signal**: ITB dynamic
  prices peak 8–9 a.m. EB; revenue growth $22M (2022) → $34M (2023) →
  ~$40M (2024) ([DC News Now](https://www.dcnewsnow.com/stretch-your-dollar/i-66-tolls-bring-in-millions-a-year-as-drivers-shy-away-from-pricey-commutes/)) —
  usable as a demand-trend covariate and a mode/route-choice observable.
- OTB usage "increasing month-over-month across vehicle classes incl.
  freight" — concessionaire self-report, promotional trust level.
- HOV-2+ exemption + Vienna Metro access at Nutley couple the corridor to
  transit/carpool demand — a person-throughput (POL-2) corridor par
  excellence.

## The natural experiment CBI should exploit

The **-54% express travel time / "GP lanes also improved"** claim comes
from the concessionaire ([ride66express](https://ride66express.com/news/revolutionizing-mobility-the-success-of-the-66-express-outside-the-beltway/))
— trust level *promotional*. This is precisely a CBI before/after token
job: 2019-vintage vs 2023+ detector data → duration, deficit-area, and
stability tokens per bottleneck, with the induced-demand caveat front and
center (the I-405 Sepulveda lesson). Until then the claim stays
`corridor_context`, never a benefit statement.

## What AMS modeling needs next (the data-acquisition list)

1. **Detector/probe data**: VDOT NoVA detectors and/or INRIX/RITIS probe
   for I-66 (the NVTA I-395 private-path pipeline already handles the
   INRIX format — same loader, `min_confidence=30`). Two eras minimum:
   pre-2022 and post-2023.
2. **GMNS network**: OSM extract I-495↔Gainesville with managed-lane
   separation (EL vs GP as parallel links), era-stamped; Nutley/Rt-28
   interchange geometry.
3. **Toll/transaction series** (public reports) as demand covariates.
4. Then: CBI diagnosis per era → observed tokens → No-Build/Build
   comparison against the concession claims → calibration targets for the
   DTA scheme ([../../schemas/ams_scheme_i66_draft.yml](../../schemas/ams_scheme_i66_draft.yml)).
