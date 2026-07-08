# I-10 & I-405 RAG corroboration — the full loop (2026-07-08)

Second Evidence-Compiler run, this time on the two corridors where we
**hold real detector data** in-repo. Unlike the [I-66 run](I66_CORRIDOR_KNOWLEDGE.md)
(text-only, everything `needs_detector_check`), here the web claims are
**confirmed by our own detector diagnosis** — so confidence rises past the
text-only ceiling and the issues move to `needs_planner_review`. This is
the compiler doing exactly what the memo demands: *text suggests, data
confirms.*

Machine-readable outputs:
[i10_fused_issue_graph.json](i10_fused_issue_graph.json),
[i405_fused_issue_graph.json](i405_fused_issue_graph.json); sources in
[source_registry.json](source_registry.json).

## The contrast, in one table

| corridor | detector data in-repo? | web claim | fused confidence | status |
|---|---|---|---|---|
| **I-66** | no | Nutley St / Rt 28 bottlenecks | 0.68 (agency-text cap) | `needs_detector_check` |
| **I-10** | yes (PeMS Mar 2018) | "downtown #3 US bottleneck" | **0.95** | `needs_planner_review` |
| **I-405** | yes (PeMS Mar 2018) | "most congested in CA; Sepulveda Pass" | **0.93** | `needs_planner_review` |

I-10 hits 0.95 — the **benchmark-reproduction + detector** ceiling (both
corridors reproduce under `repro_gates`); nothing text-only can reach it.

## I-10 (Santa Monica Freeway)

- Web: the downtown LA I-10 ranked **#3 in US bottleneck severity**
  (American Highway Users Alliance, via [LAist](https://laist.com/news/kpcc-archive/the-worst-traffic-bottlenecks-in-los-angeles-count));
  all three freeway-to-freeway interchanges routinely top-10; peak
  6:30–9:30a and from 4p ([worst-freeways roundup](https://noviklawgroup.com/blog/5-la-freeways-we-love-to-hate/)).
- Detector: our in-repo PeMS diagnosis found **11 recurring-bottleneck
  issues** across the sampled sensors — the text bottleneck claim
  corroborated, confidence lifted to 0.95.
- Congestion-pricing under study for DTLA/I-10 ([Urbanize LA](https://la.urbanize.city/post/metro-considers-congestion-pricing-dtla-i-10-freeway-santa-monica-mountains)) —
  a demand-management scenario CBI before/after tokens are built to test.

## I-405 (San Diego Freeway)

- Web: "most congested highway in California," Sepulveda Pass among the
  nation's worst; ExpressLanes + a parallel transit corridor proposed
  I-10↔US-101 ([Wikipedia](https://en.wikipedia.org/wiki/Interstate_405_(California)),
  [LA Metro](https://www.metro.net/projects/i-405-expresslanes-project/),
  [Caltrans D7](https://dot.ca.gov/caltrans-near-me/district-7/district-7-projects/d7-i405-sepulveda-expresslanes));
  recurring NB weekend rehab closures ([WestsideToday](https://westsidetoday.com/2026/05/15/caltrans-warns-of-massive-northbound-i-405-lane-closures-through-sepulveda-pass-this-weekend/)).
- Detector: **4 recurring-bottleneck issues** in the sampled sensors →
  fused confidence 0.93.
- The Sepulveda transit-corridor proposal is a **person-throughput
  scenario** (POL-2) — the vehicle-speed severity metric would misjudge it;
  flagged for the planner.

## Why this matters for CBI / AMS modeling

1. **Demand-side priors, corroborated.** The web establishes *where* and
   *when* demand concentrates (interchanges, Sepulveda Pass, peak windows);
   the detectors confirm the recurring bottlenecks sit exactly there. That
   gives the AMS scheme validated bottleneck locations to seed a subarea
   and to check assignment output against.
2. **Early simulation targets.** Each corroborated issue carries
   `COMPARE_WITH_BENCHMARK` and `GENERATE_CORRIDOR_DASHBOARD` recommended
   tokens — these become the No-Build calibration targets before any Build
   scenario is simulated.
3. **Scenario hypotheses named, not assumed.** DTLA/I-10 congestion
   pricing and the I-405 Sepulveda transit corridor are recorded as
   scenario *hypotheses to test*, with the person-throughput and
   induced-demand caveats attached — never as foregone benefits.
4. **The firewall held.** Every fused issue is
   `status: needs_planner_review`, `reader_role: transportation_reader` —
   the RAG produced structured issues for a human to approve, and touched
   no network and no code.

## Method note

`api.load_pems` → `api.diagnose` (8 sensors, n_boot=8 — enough to classify,
not to tighten a CI) → `api.build_issue_graph` → `api.compile_evidence(...,
detector_graph=dg, benchmark_pass=True)`. Confidence ceilings enforced per
[RAG_EVIDENCE_COMPILER.md](../RAG_EVIDENCE_COMPILER.md) Contract 4.
