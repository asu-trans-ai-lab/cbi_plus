# INTELLECTUAL_LINEAGE — who stands behind this platform, and who writes what

*Background companion to [INTRODUCTION.md](INTRODUCTION.md) and
[MISSION.md](MISSION.md): the theory lineage with references, the allies map,
and the authorship/division-of-labor principle. Internal document.*

---

## 1. The authorship principle

The Introduction is **not a literature review and not a student assignment**.
It is a paradigm statement:

```
old traffic engineering:
  PHF / V/C / LOS / hourly averages / plotting
new traffic engineering:
  high-resolution data / dynamic congestion / Newell–Daganzo physics /
  CBI–QVDF / explainable AI / benchmark validation
```

That framing is set by the principal architect (Simon). Students and
collaborators prepare the supporting materials **after** the framing is
fixed — benchmark tables, key figures, the glossary, the six contracts,
reproducible commands, known failure cases, and V/C-vs-dynamics examples.
(Most of these already exist in this repo; see the pointer table in §5.)

### Division of labor

| Role | Who | Task |
|---|---|---|
| Chief architect / senior author | Simon Zhou | mission, paradigm shift, teaching philosophy |
| CBI engineering line | David Hale / FHWA CBI community | CBI workflow, RITIS/CBI field experience, engineering language |
| QVDF / FD / theory checking | Mohammad Abbasi | QVDF, FD, capacity, μ/C, D/C-hours, speed–volume conventions |
| Benchmark reproduction lead | Henan Zhu | I-10 / I-405 / I-395 benchmarks, figures, gates, reproducibility |
| Data & mapping | Yajun Liu / Jinxi Wu | PeMS, CV/GPS, corridor mapping, CBI index, sensor/link matching |
| Tool engineering | Han Zheng / tool-oriented students | six contracts, input/output schemas, one-command reproduction |
| Curriculum & dissemination | Ram Pendyala / Hua Wei | curriculum packaging, training, AI-native transportation education |

---

## 2. The intellectual foundation — inherit, do not claim

The Introduction must never read as "we invented everything." The correct
statement:

> **We inherit the Newell–Daganzo–Berkeley/MIT dynamic traffic-flow
> tradition, and turn it into a data-driven, AI-assisted,
> benchmark-validated engineering-education platform.**

| Person / school | Place in the Introduction | Background link |
|---|---|---|
| **LWR** (Lighthill–Whitham 1955; Richards 1956) | the conservation-law foundation: traffic is dynamic flow, not static V/C | [Lighthill & Whitham, *On kinematic waves II*](https://courses.physics.ucsd.edu/2018/Fall/physics218a/Whitham_Lighthill%20Traffic%20Waves.pdf) |
| **Gordon Newell** | cumulative curves, simplified kinematic wave theory, queue timing (the direct ancestor of T0/T2/T3/P/μ) | [Newell 1993, *A simplified theory of kinematic waves, Part I*](https://www.sciencedirect.com/science/article/abs/pii/019126159390038C) |
| **Carlos Daganzo** (UC Berkeley, Professor of the Graduate School) | CTM, sending/receiving flow, network queue propagation — the engine in `engines/ctm_python` | [Berkeley CEE profile](https://ce.berkeley.edu/people/faculty/daganzo) · [CTM Part II](https://www.sciencedirect.com/science/article/pii/019126159400022R) |
| **Michael Cassidy** (UC Berkeley) | the experimental bottleneck / freeway-operations tradition — the empirical discipline behind our episode audits | [Berkeley ITS profile](https://its.berkeley.edu/people/michael-cassidy) |
| **Moshe Ben-Akiva** (MIT) | DTA, demand–supply interaction, real-time simulation (DynaMIT tradition) — the demand-side line our forward-only OD stance respects | [MIT CEE profile](https://cee.mit.edu/people_individual/moshe-e-ben-akiva/) |
| **Hani Mahmassani** (Northwestern, *in memoriam*, d. July 2025) | DTA, network dynamics, real-time traffic management — cite as intellectual legacy | [Northwestern memorial](https://www.mccormick.northwestern.edu/news/articles/2025/07/professor-hani-mahmassani-passes-away/) |
| **Jorge Laval** (Georgia Tech) | the traffic-flow-theory + complex-systems + ML bridge — the closest living kin to "AI constrained by traffic-flow physics" | [Georgia Tech profile](https://ce.gatech.edu/directory/person/jorge-laval) |

---

## 3. Allies, and what we actually compete with

### Potential allies (never framed as rivals)

| Community | Why they are allies | Link |
|---|---|---|
| Berkeley traffic-flow line (Daganzo / Cassidy / ITS) | the orthodox Newell–Daganzo foundation | above |
| MIT DTA / demand–supply line (Ben-Akiva, DynaMIT) | demand, assignment, real-time prediction | above |
| Georgia Tech congestion + ML line (Laval et al.) | theory + ML + operations + simulation | above |
| **RITIS / UMD CATT Lab** | real-world agency dashboards, probe data, bottleneck tools — an operational-data partner and benchmark reference, *not* a competitor | [RITIS](https://www.cattlab.umd.edu/ritis/) · [Probe Data Analytics Suite](https://www.cattlab.umd.edu/probe-data-analytics-suite/) |
| FHWA / DOT / MPO agencies (FHWA CBI team, ADOT, MAG, NVTA, VDOT) | real problems, real data, real validation pressure | — |
| Zephyr / GMNS open-source planning community | curriculum and tool diffusion | — |

Note on RITIS/CATT: their probe-data bottleneck dashboards define bottlenecks
by speed thresholds — genuinely valuable engineering tools, and exactly the
point where this platform adds the next layer: **a speed-threshold bottleneck
is not enough; we contribute mechanism-based active/passive diagnosis**
(stage-6 classes, μ/C, wave direction).

### The real competition: three weak paradigms, not people

| Competing paradigm | Its limitation |
|---|---|
| Static HCM / LOS / V/C-only education | teaches indicator arithmetic, not dynamic congestion diagnosis |
| Plot-driven big-data dashboards | many figures, no explanation of where the queue comes from, where it goes, or whether the bottleneck is active |
| Black-box AI / RL / digital-twin hype | can predict or control, but with no physics gate and no benchmark validation — easy to misuse |

> We are not competing with textbooks, dashboards, or AI tools directly.
> **We are competing with a weak way of thinking: plotting without mechanism,
> prediction without diagnosis, and simulation without validation.**

---

## 4. The Introduction's four-paragraph skeleton

Implemented in [INTRODUCTION.md](INTRODUCTION.md):

1. **Problem** — education still leans on PHF / V/C / LOS / hourly averages;
   useful but insufficient for dynamic congestion diagnosis.
2. **Intellectual foundation** — LWR conservation law; Newell's cumulative
   curves and simplified kinematic waves; Daganzo's CTM and network
   propagation; the broader Berkeley/MIT/Northwestern DTA and operations
   tradition.
3. **Modern gap** — students run Python/dashboards/ML/RL but cannot say
   whether a low-speed segment is an active bottleneck, passive queue,
   incident, spillback, or data artifact.
4. **Our mission** — CBI/QVDF as the platform connecting high-resolution
   data, traffic-flow physics, benchmark validation, and explainable AI.

---

## 5. Directive to the team (send as-is)

> For the Introduction, please do not write a generic literature review. The
> goal is to define a paradigm shift in traffic-engineering education and
> practice.
>
> The intellectual foundation should be clearly stated as the dynamic
> traffic-flow line: the LWR conservation law, Newell's cumulative-curve and
> kinematic-wave interpretation, Daganzo's CTM and network queue propagation,
> and the broader Berkeley/MIT/Northwestern tradition in dynamic traffic
> assignment, operations, and real-time traffic management.
>
> The problem we are addressing is not simply a missing software tool. The
> problem is that many students can generate plots, run Python, use
> dashboards, or apply AI models, but they cannot diagnose congestion
> mechanisms. They confuse low speed with bottleneck, V/C with congestion,
> hourly averages with dynamic queue evolution, and simulation output with
> validated engineering knowledge.
>
> The CBI/QVDF platform should therefore be framed as a training and
> validation platform for a new generation of traffic engineers. It connects
> high-resolution data, queue diagnosis, active/passive bottleneck
> classification, capacity drop, QVDF calibration, benchmark gates, and
> explainable AI-assisted decision support.
>
> Please prepare supporting materials only after this framing is fixed:
> benchmark figures, the glossary, the six contracts, I-10/I-405/I-395
> validation tables, and examples showing why static V/C and average plots
> are not enough.

**Where those supporting materials already live in this repo:**

| Material the team owes | Already here |
|---|---|
| benchmark figures & validation tables | `benchmarks/qvdf_paper_i10`, `qvdf_paper_casestudy2`, `benchmark_expected/actual_statistics.csv` |
| glossary | `docs/GLOSSARY.md` |
| six contracts | `docs/CONTRACTS.md` |
| reproducible commands | README ladder + `repro_gates` |
| known failure cases | `docs/FIXES_CBI_PLUS_2026-07-07.md`, `docs/LESSONS_LEARNED.md` |
| V/C-vs-dynamics examples | `docs/teaching/THEORY_FOUNDATIONS.md` |

---

## 6. The bottom line

> **You are not missing a writer. You are missing the organizational
> structure that upgrades "students writing code" into "a team building a
> new traffic-engineering paradigm together."**

Thought and Introduction: the architect leads. Theory checking: Mohammad +
David Hale + senior traffic-flow friends. Benchmarks and figures: Henan /
Jinxi / Yajun / the tool students. Curriculum and dissemination: Ram / Hua /
the DOT workshop network. External intellectual allies: Berkeley / MIT /
Georgia Tech / RITIS-CATT / the FHWA-DOT community.

## References

1. Lighthill, M.J., Whitham, G.B. (1955). On kinematic waves II: A theory of
   traffic flow on long crowded roads. *Proc. Royal Society A* 229.
   https://courses.physics.ucsd.edu/2018/Fall/physics218a/Whitham_Lighthill%20Traffic%20Waves.pdf
2. Newell, G.F. (1993). A simplified theory of kinematic waves in highway
   traffic, Part I. *Transportation Research Part B* 27(4).
   https://www.sciencedirect.com/science/article/abs/pii/019126159390038C
3. Daganzo, C.F. (1995). The cell transmission model, Part II: Network
   traffic. *Transportation Research Part B* 29(2).
   https://www.sciencedirect.com/science/article/pii/019126159400022R
4. UC Berkeley CEE — Carlos F. Daganzo.
   https://ce.berkeley.edu/people/faculty/daganzo
5. UC Berkeley ITS — Michael Cassidy.
   https://its.berkeley.edu/people/michael-cassidy
6. Georgia Tech CE — Jorge A. Laval.
   https://ce.gatech.edu/directory/person/jorge-laval
7. MIT CEE — Moshe E. Ben-Akiva.
   https://cee.mit.edu/people_individual/moshe-e-ben-akiva/
8. Northwestern McCormick — Professor Hani Mahmassani Passes Away (July 2025).
   https://www.mccormick.northwestern.edu/news/articles/2025/07/professor-hani-mahmassani-passes-away/
9. UMD CATT Lab — RITIS. https://www.cattlab.umd.edu/ritis/
10. UMD CATT Lab — Probe Data Analytics Suite.
    https://www.cattlab.umd.edu/probe-data-analytics-suite/
11. Zhou, Cheng, Wu et al. (2022). Multimodal Transportation 1, 100017 —
    reproduced at `benchmarks/qvdf_paper_i10/`.
