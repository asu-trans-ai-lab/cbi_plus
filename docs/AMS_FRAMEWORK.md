# Agentic AI for Translational AMS Modeling
### A scheme-driven, engine-agnostic, and quality-gated framework for open, reproducible corridor and subarea simulation

*The top-line framework this platform instantiates. CBI/QVDF (this repo) is
the first working instance — the corridor-diagnosis stage of the wider AMS
(Analysis, Modeling, and Simulation) workflow.*

---

## The problem is not methodology — it is fragmentation

Over the past 10–20 years the transportation modeling community has
accumulated many correct methodologies, calibration practices, tool-specific
procedures, and expert tricks. But these remain fragmented across reports,
emails, proprietary workflows, project folders, and analyst memory:

- every team has its own ad-hoc tools;
- every tool has its own inputs and outputs;
- even the flowchart is not fully agreed upon across teams;
- exceptions and calibration tricks are not structurally recorded;
- downstream never knows upstream's assumptions;
- reviewer comments go into email and never become machine-checkable gates;
- engines cannot actually talk to each other.

This is the old AMS/MRM disease. The cure is not another tool. The cure is a
**scheme file + explicit contracts + quality gates + reproducible artifacts**,
with **agentic AI as the orchestration layer** — so that any engine
(TransModeler, SUMO, DTALite, DLSIM, Aimsun, VISSIM, …) can participate, and
no engine can monopolize the workflow.

## The five principles

### Principle 1 — Scheme-first, not tool-first

Do not pick a software package and force every question into it. First
declare the scheme:

```
use case · network · demand · subarea · policy · behavioral assumptions
kernel options · trajectory export · calibration targets · quality gates
visualization outputs · review comments
```

Then any engine executes against that scheme. The scheme is the foundation.
(Working example: `schemas/ams_scheme_example.yml` in this repo.)

### Principle 2 — Engine-agnostic, but not engine-loose

Engines matter — but every engine speaks through common contracts:

```
GMNS network contract · OD/demand contract · trajectory/event contract
CBI validation contract · scenario/policy contract · quality-gate contract
```

TransModeler can be an engine. SUMO can be an engine. DTALite/DLSIM can be
an engine. The requirement is interoperability, and the red line is:

> **No engine should become the whole workflow.**

Otherwise AMS gets locked into one proprietary pipeline. (This repo's
concrete instance: `docs/ENGINES.md` — 12 engines, one corridor contract,
native formats preserved, staged coupling.)

### Principle 3 — Agentic AI is the orchestration layer

AI's value here is not writing code snippets. It is:

```
read documents → understand assumptions → generate the scheme file
→ check data readiness → call conversion tools → run kernels
→ inspect logs → detect exceptions → summarize failures
→ update quality gates → record expert comments
→ produce reproducible artifacts
```

Agentic AI = workflow controller + documentation reader + QA assistant +
exception tracker + reproducibility manager. (This entire repo was built and
audited in exactly this mode — including two independent AI review agents
whose findings became code fixes and gates.)

### Principle 4 — Expert comments become gates, not emails

When an expert is right, the insight must not live only in an email thread.
Every comment enters a register and links to a checkable gate:

```
expert_gap_validation_register.csv   quality_gates.json
assumption_register.yml              open_issues.md
```

Twenty years of experience, tricks, and concerns get registered, checked,
and tracked — never "the expert said so once, then nobody followed up."
(This repo's instances: the external review → `docs/FIXES_*.md` → gates;
the student read-through → `docs/reviews/` → applied fix list;
the positioning memo → `docs/ADOPTION_TRACE.md` with ENFORCED/GAP statuses.)

### Principle 5 — The deliverable is a reproducible process, not a PDF

The final handoff is not a report. It is:

```
scheme file · run folder · quality gates · trajectory outputs
CBI scorecard · GUI visualization · expert comment register · comparison memo
```

so others can rerun it, swap the engine, extend the policy, and inspect every
step. (This repo's instance: every benchmark folder + `repro_gates`.)

## The external position statement (memo-ready)

> Our intent is not to promote a closed ecosystem or to claim that one
> open-source engine can replace every established commercial tool. The more
> important design principle is that AMS/MRM workflows should become
> scheme-driven, engine-agnostic, and reproducible.
>
> Our proposal is to use an agentic AI-enabled AMS framework to organize this
> process around a common scheme file, explicit data contracts, quality
> gates, and reproducible artifacts. TransModeler, SUMO, DTALite, DLSIM,
> Aimsun, VISSIM, or other engines can all participate. The key requirement
> is not that everyone use the same engine, but that each engine can read
> from and write to a shared interoperable workflow contract.
>
> We are not only discussing methodology. We are turning methodology, expert
> experience, and review comments into machine-checkable workflow objects.
> The open-pipeline effort should be judged not by whether one engine is
> faster than another, but by whether the workflow is transparent,
> reproducible, extensible, and interoperable — supporting translational AMS
> modeling from regional planning models to corridor/subarea analysis,
> dynamic assignment, trajectory/event outputs, CBI validation, policy
> evaluation, and visualization, in a process other analysts can inspect
> and rerun.

## The 30-second meeting version

> I do not want this to become a tool-vs-tool debate. The real issue is
> workflow interoperability. We have 20 years of AMS/MRM methods locked in
> ad-hoc scripts, proprietary workflows, and undocumented calibration tricks.
> Our contribution is an agentic AI-enabled, scheme-driven AMS pipeline where
> different engines participate — but every engine speaks through the same
> data contract, trajectory contract, policy contract, and quality-gate
> system. The goal is not to sell an ecosystem. The goal is to make
> translational AMS modeling reproducible, reviewable, and extensible.

## The anchor sentence

> **The engine is replaceable; the scheme, contracts, gates, and
> reproducible process are the foundation.**

## Where this repo sits in the AMS chain

```
regional planning model
  → subarea / corridor extraction        (gmns_transfer, osm2gmns, adapters)
    → dynamic assignment / simulation    (DTALite / DLSIM / CTM / any engine)
      → trajectory & event outputs       (trajectory contract)
        → CBI validation & diagnosis     (THIS REPO: episodes, μ/C, ranking, gates)
          → policy evaluation            (QVDF parameters → planning models)
            → visualization & review     (gui4gmns, dashboards, DEV_STATUS)
```

Scope statement (so the chain is honest): CBI/QVDF is a **one-pass
diagnostic** — it consumes observed states or assignment output and does
not close a demand–supply equilibrium loop (no route/departure-time
response feeds back through it). Equilibration lives in the assignment
stage; multi-engine assignment integration is roadmap, not yet
demonstrated end-to-end in this repo.

CBI/QVDF is the validation-and-diagnosis stage, already fully scheme-driven
(six contracts), engine-agnostic (12-engine registry, two arenas), and
quality-gated (25/25 reproduction gates). The same pattern now scales up the
chain.
