# MISSION — what the CBI/QVDF platform is, and is not

*Send this to every student and collaborator before they write a line of code.*

This tool is **not** a data-processing script, and not a machine that runs
PeMS/INRIX/NVTA data and prints piles of figures. It is a **next-generation
traffic-engineering training and verification platform**, built to answer the
most basic and most difficult question in our field:

> **Do we actually understand freeway congestion and bottlenecks?**

Most traffic-engineering textbooks teach static indicators; most AI tools do
labels, prediction, reinforcement learning, or big-data pattern recognition.
But without understanding congestion formation, active bottlenecks, passive
queues, capacity drop, queue propagation, D/C, QVDF, and observed-data
calibration, AI is a black box and simulation is guesswork.

**Think of yourselves as medical students.** A medical student cannot only
read textbooks, and cannot only run models. You must see real cases and
understand symptoms, mechanism, diagnosis, treatment, and risk. Likewise, a
traffic engineer cannot only run software. You must be able to read a freeway
corridor and answer: how did this congestion form? Where is the bottleneck?
Is the queue active or passive? Is there a capacity drop? Does demand exceed
capacity? Do the model parameters have physical meaning? And can the result
be verified against real data?

Therefore the platform must have **stable inputs, stable outputs, stable
benchmarks**. We are not building a messy tool, and we are not "outputting
all PeMS results." We are building a tool that trains students, verifies
theory, and supports engineering judgment.

## The seven operating principles

1. **Define the input contract first.** Every corridor input must state
   detector/TMC/link IDs, direction, lane counts, time resolution, speed /
   flow / density, observed-vs-imputed flags, period definitions, weekday
   filters, units, and the coordinate/reference system. No input contract,
   no calibration. (Spec: `docs/CONTRACTS.md`.)

2. **Run the benchmarks before running all the data.** The I-10 (paper),
   I-405 (CA PeMS), and I-395/NVTA benchmarks must reproduce stably — each
   with expected statistics, tolerances, pass/fail gates, and previous-run
   comparison. Without benchmark reproduction, the tool cannot be called
   correct. (`python -m cbi_pipeline.repro_gates`.)

3. **Distinguish active bottlenecks from passive queues.** Low speed is not
   automatically a bottleneck: it can be upstream/downstream spillback, an
   incident, merge/diverge friction, an imputation artifact, or a passive
   queue. The tool outputs a **bottleneck type**, not just a congestion map.
   (Stage 6 classes: active_bottleneck / queued_passive / spillback_source /
   isolated_uncertain.)

4. **State the aggregation level of every number.** Per-day episodes identify
   real queue formation. Average-weekday patterns make stable benchmarks.
   AM/MD/PM/MDPM periods are analysis windows, not physical events. Every
   output labels itself: single day, average weekday, sensor-period, or
   corridor-level aggregate. (The `aggregation_level` column is mandatory.)

5. **Traffic-flow physics gates on everything.** Speed, flow, density,
   capacity, μ/C, D/C, queue duration, T0/T2/T3, FD fit, and the QVDF speed
   reconstruction all have sanity checks. Any corridor-period whose
   speed-profile MAE exceeds 10 mph is marked FAIL — never blended into the
   results. (`cbi_pipeline.benchmark_gates`.)

6. **The CBI ranking is the deliverable.** If the tool is called a
   CBI tool it must output the bottleneck score, ranking, top locations,
   active/passive labels, confidence, and comparison with the previous
   benchmark. No ranking table, no complete tool. (Stage 6 outputs.)

7. **A new student must be able to learn it — not only the author run it.**
   README, GLOSSARY, the hello-world case, the one-sensor-one-day exercise,
   and the three benchmark cases form a learning ladder. A first-year student
   climbs from data, figures, formulas and gates to congestion understanding
   — without being stopped by broken paths or terminology chaos. (Audited by
   the simulated-reader reviews in `docs/reviews/`.)

## The goal

Not "the code runs." The goal is:

> **Retrain the next generation of traffic engineers on real freeway data,
> so they combine traffic-flow theory, simulation, AI, and engineering
> judgment.**

If this gate is not passed, there is no meaningful digital twin, digital
infrastructure, reinforcement learning, or AI traffic management. Without
congestion understanding, every advanced AI is surface work.

## The one sentence to remember

> **AI does not replace traffic-flow theory. AI must be constrained,
> explained, and verified by traffic-flow theory.**

Without that constraint, AI will treat imputed data as truth, passive queues
as bottlenecks, average weekdays as physical episodes, speed drops as
capacity drops, and pretty figures as engineering judgment. Preventing
exactly these mistakes is what this platform is for — and every one of them
is a gate in the code, not a slogan. (Theory foundations:
`docs/teaching/THEORY_FOUNDATIONS.md`.)
