# Web-RAG bottleneck knowledge notes — 2026-07-08

Live web knowledge-gathering run for the corridors this platform diagnoses,
plus the travel-demand-modeling knowledge base the CBI/QVDF bridge speaks
to. Every claim carries its source; extracted text issues live in the
fused Issue Graph (`outputs/web_rag/fused_issue_graph.json`, regenerable —
outputs/ is untracked).

## What the web says about OUR corridors (and what our detectors say back)

### I-405 Sepulveda Pass (matches our I-405N v4 + PeMS 2018 benchmarks)

- Reported as possibly "the worst freeway segment in California"; worst
  delays NB 3–4 p.m., average speeds down to ~19 mph; the $1.1B widening
  is widely reported as having not fixed congestion
  ([LA Weekly](https://www.laweekly.com/1-1-billion-and-five-years-later-the-405-congestion-relief-project-is-a-fail/),
  [NBC LA](https://www.nbclosangeles.com/news/traffic-on-405-freeway-got-worse-since-expansion-project-study-shows/81493/)).
- Ongoing pavement rehabilitation with recurring weekend NB lane
  reductions through the Pass
  ([Caltrans D7](https://dot.ca.gov/caltrans-near-me/district-7/district-7-projects/d7-i405-sepulveda-expresslanes),
  [Hoodline](https://hoodline.com/2026/03/sepulveda-pass-slog-405-squeezed-all-weekend-for-pavement-work/)).
- **Cross-corroboration result**: the text Reader extracted a
  `recurring_congestion_report` (I-405 NB, PM window) from this coverage;
  `api.corroborate` matched it to our detector-diagnosed I-405
  `recurring_bottleneck` issue — confidence 0.60 → 0.75. The
  "widening didn't fix it" storyline is exactly the induced-demand caveat
  our benefit tokens carry.

### I-17 (matches our AZ INRIX benchmark + the SPR-790 flex-lanes use case)

- ADOT opened Arizona's first flex lanes: an 8-mile reversible two-lane
  roadway between Black Canyon City and Sunset Point, plus a third GP lane
  Anthem Way → Black Canyon City (15 mi); project at substantial completion
  ([ADOT blog](https://azdot.gov/adot-blog/arizonas-first-flex-lanes-are-coming-take-look-how-they-will-operate),
  [Improving I-17](https://www.improvingi17.com/),
  [ADOT news](https://azdot.gov/news/i-17-improvement-project-reaches-substantial-completion-milestone)).
- Motivation matches our CBI framing: a recurring directional bottleneck
  where terrain makes conventional widening costly — precisely the
  No-Build/Build token-comparison case (observed CBI targets → flex-lane
  Build run).

## Travel-demand-modeling knowledge (the CBI/QVDF bridge)

Q&A distilled from the literature sweep — the same ground the
"Ask Me About Travel Demand Modeling" GPT covers (live dialogue pending
browser connection; script in
[../reviews/EXTERNAL_GPT_DIALOG_2026-07-08.md](../reviews/EXTERNAL_GPT_DIALOG_2026-07-08.md)):

**Q: Why can't standard travel demand models see our bottlenecks?**
A: The BPR volume-delay function is a smooth monotone map from v/c to
delay — chosen for closed-form integrability in user-equilibrium
assignment, not for physics. Real speed-flow data is U-shaped and
capacity-drops at breakdown, contradicting BPR's assumptions exactly
where bottlenecks matter (v/c ≥ 1)
([NCDOT TDM calibration](https://connect.ncdot.gov/projects/planning/TPB%20Model%20User%20Groups/Group%20Meeting%20-%20April%2027,%202011%20Calibrating%20TDM%20Volume-Delay%20Functions%20Using%20Bottleneck%20-%20Queuing%20Analysis.pdf),
[MTC VDF validation vs PeMS](http://bayareametro.github.io/pems-typical-weekday/vdf_validation/)).

**Q: What does static assignment assume that CBI observes to be false?**
A: (1) delay stays within the link — no queue spillback upstream; (2)
congestion is constant within each broad time period
([TF Resource — Delay Estimation](https://tfresource.org/topics/Delay_Estimation_in_Trip_Based_Models.html)).
CBI's episode objects (T1 onset, T3 recovery, upstream tail growth)
measure both violations directly.

**Q: What are modelers doing about it?**
A: FD-based modified VDFs
([Modified VDF, 2023](https://www.researchgate.net/publication/375171137_Modified_Volume-Delay_Function_Based_on_Traffic_Fundamental_Diagram_A_Practical_Calibration_Framework_for_Estimating_Congested_and_Uncongested_Conditions)),
residual-queue static assignment
([arXiv 2501.06573](https://arxiv.org/pdf/2501.06573)), BPR variants with
demand fluctuation + capacity degradation
([Analytical BPR extension](https://www.researchgate.net/publication/337010410_Analytical_Model_for_Travel_Time-Based_BPR_Function_with_Demand_Fluctuation_and_Capacity_Degradation)).
**This is the QVDF pitch verbatim**: calibrated D/C→duration and
D/C→worst-speed laws are exactly the "queue-aware VDF" this literature is
reaching for — with our elasticities being field-calibrated, not assumed.

**Improvement items adopted** (register KNW-1..3): position QVDF
explicitly as the queue-aware VDF answer in INTRODUCTION/AMS bridge text;
cite the modified-VDF/residual-queue literature in INTELLECTUAL_LINEAGE;
the induced-demand caveat gains the I-405 widening story as its concrete
public example.

## Method note

Pipeline: `WebSearch` sweep → source-attributed snippets →
`api.extract_issues_from_texts` (rule-based reference extractor; an LLM
front-end can replace it — the Issue Graph schema still disposes) →
`api.corroborate` against detector issues → fused graph for Planner
review. Text-only confidence is capped at 0.85; corroboration by
detectors raises it; uncorroborated reports are flagged
`needs_detector_check` — a question for the Planner, never a fact.
