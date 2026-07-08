# AI Participant Simulation Protocol for CBI/CPI/QVDF PyPI Release

**A structured audit loop for IEEE Big Data-style participants, tool learning, benchmark calibration, dashboard feedback, bug fixing, and traceability**  
**Prepared for release-readiness tracking | 2026-07-08**

## 1. Purpose

Once the PyPI package is released, we should not rely only on the development team's internal tests. We should simulate how external AI-assisted participants, such as IEEE Big Data competition teams, first-year transportation students, data-science users, agency analysts, and software developers will actually discover, install, learn, run, debug, and extend the tool.

The goal is not to blame users or competitors. The goal is to learn from different perspectives, expose weak onboarding paths, discover missing functions, and turn confusion into a prioritized development backlog.

**Core principle:** a reliable CBI/CPI/QVDF package must help users move from data and code to congestion understanding, benchmark validation, and decision support.

## 2. Soft collaborative positioning

Use this language in the README, slides, and issue templates:

> We are all friends in the broader traffic-engineering, AI, and data-science community. Different groups bring different perspectives: theory, operations, dashboards, machine learning, simulation, agency practice, and open-source engineering. Our goal is to learn from those perspectives and make the tool more reliable, explainable, and useful.
>
> We are not competing against individual scholars, labs, or tools. We are trying to improve a shared workflow: from static plotting to mechanism-based, data-driven, benchmark-validated traffic engineering.

## 3. Simulation personas

| Agent | Background | What they test | Expected pain points |
|---|---|---|---|
| A1. First-year transportation MS student | Basic Python, no traffic-flow theory | Install, glossary, hello-world, T0/T2/T3 interpretation | Terminology, units, active vs passive bottleneck |
| A2. AI / Kaggle-style competitor | Strong Python/ML, weak traffic theory | Data loading, feature engineering, model submission | Treating speed drops as labels without mechanism |
| A3. DOT / MPO analyst | Practical performance-measure background | Average weekday patterns, bottleneck ranking, corridor reports | Need explainable outputs and trusted thresholds |
| A4. Traffic-flow researcher | Strong theory | FD/QVDF calibration, capacity, discharge rate, D/C-hours | Physical validity, units, benchmark reproducibility |
| A5. Software developer | Packaging and CI/CD | PyPI install, CLI, APIs, reproducibility, error messages | Broken paths, unclear schemas, missing dependencies |
| A6. Dashboard/UI user | Wants visual insight | Panels, maps, time-series, queue profiles, export features | Too many plots, not enough guided diagnosis |
| A7. RL / digital twin user | AI control perspective | Scenario inputs, state/action/reward features, physics gates | Black-box control without congestion diagnosis |

## 4. End-to-end participant journey

### Stage 0 - Release front door

1. Install package from PyPI.
2. Import package in Python.
3. Run `--help` for the CLI.
4. Run the smallest reproducible example.
5. Confirm that the package prints version, data path, output path, and next action.

**Pass gate:** a clean environment can reach first successful output in less than 15 minutes.

### Stage 1 - Learning the engines

Users should learn the tool in this order:

1. **Glossary and mission** - what problem the package solves.
2. **FD engine** - speed, flow, density, capacity, critical speed, observed/imputed status.
3. **CBI/CPI engine** - congestion episodes, T0/T2/T3, active/passive bottleneck, bottleneck ranking.
4. **QVDF engine** - D/C-hours, queue duration P, discharge rate mu, capacity C, speed reconstruction.
5. **Benchmark gate engine** - expected vs actual statistics, tolerance, pass/fail summary.
6. **Dashboard/report engine** - figures, panels, summaries, export package.
7. **Developer feedback loop** - issue templates, missing functions, feature requests, reproduction logs.

### Stage 2 - Benchmark learning path

| Step | Dataset / case | Purpose | Must output |
|---|---|---|---|
| 1 | Toy / one-sensor one-day | first traffic-flow diagnosis | speed-flow-density plot, T0/T2/T3 |
| 2 | I-10 paper benchmark | QVDF theory hello-world | FD, D/C-to-P, reconstructed speed, tolerance table |
| 3 | I-405 PeMS benchmark | high-resolution detector-based congestion | observed/imputed mask, queue profile, FD/QVDF calibration |
| 4 | I-395 / NVTA benchmark | planning-level bottleneck and corridor ranking | CBI/CPI ranking, QVDF folder, benchmark comparison |
| 5 | Participant-provided data | generalization test | input contract validation, dashboard, issue log |

### Stage 3 - Calibration and dashboard workflow

A participant should be able to follow this workflow:

1. Validate input contract.
2. Create average weekday profiles and per-day episodes separately.
3. Run FD calibration and physical gates.
4. Run CBI/CPI episode diagnosis.
5. Run QVDF calibration and speed reconstruction.
6. Generate dashboard figures.
7. Compare against benchmark tolerance.
8. Submit one clean feedback package to the development team.

## 5. Required gates for participant simulation

| Gate ID | Gate | Hard requirement | Evidence file |
|---|---|---|---|
| G0 | PyPI install | Package installs in a clean environment | install_log.txt |
| G1 | First output | Toy or hello-world output in <15 minutes | quickstart_output/ |
| G2 | Dependency check | No hidden dependency or private path | environment_report.txt |
| G3 | Data contract | Input schema validates before calibration | input_contract_report.csv |
| G4 | Unit consistency | Speed, flow, density, capacity, time units explicit | unit_check_report.csv |
| G5 | Observed/imputed mask | Imputed data not treated as direct measurement | data_quality_report.csv |
| G6 | FD physics | FD parameters and capacity range plausible | fd_validation.csv |
| G7 | Queue diagnosis | T0/T2/T3, P, min speed, queue length present | episode_summary.csv |
| G8 | Active/passive diagnosis | Low speed is not automatically called bottleneck | bottleneck_diagnosis.csv |
| G9 | QVDF reconstruction | Speed-profile MAE <= 10 mph hard gate | qvdf_validation.csv |
| G10 | Benchmark comparison | I-10, I-405, I-395 cases compared with tolerances | benchmark_comparison_report.csv |
| G11 | Dashboard usability | Main figures have short labels, units, and interpretation | dashboard_review.md |
| G12 | Feedback loop | Bugs and missing features filed with reproduction steps | issue_log.csv |

## 6. Feedback package submitted by each simulated participant

Each agent must submit a folder with this structure:

```text
participant_feedback/
  agent_profile.md
  install_log.txt
  environment_report.txt
  commands_run.sh
  input_contract_report.csv
  output_inventory.csv
  benchmark_comparison_report.csv
  dashboard_review.md
  bug_reports/
  missing_features/
  screenshots/
  final_readthrough_notes.md
```

## 7. Issue template for bugs and missing functions

```text
Issue title:
Agent persona:
Stage where failure occurred:
Command or notebook cell:
Dataset/case:
Expected behavior:
Actual behavior:
Error message or screenshot:
Traffic-engineering implication:
Severity: P0 / P1 / P2 / P3
Suggested fix:
Evidence files:
Reproducibility: always / sometimes / once
```

Severity guidance:

| Priority | Meaning | Example |
|---|---|---|
| P0 | Blocks release or benchmark reproduction | PyPI install fails; I-10 benchmark cannot run |
| P1 | Blocks core learning or scientific validity | units unclear; imputed data treated as observed; QVDF output missing |
| P2 | Important but not blocking | dashboard label confusing; missing explanation; slow run |
| P3 | Nice-to-have | additional export format; optional UI improvement |

## 8. Developer triage loop

Every participant issue should enter this loop:

1. **Capture** - collect command, output, screenshot, and user confusion.
2. **Classify** - bug, missing function, documentation gap, theory confusion, dashboard issue, benchmark failure.
3. **Prioritize** - P0/P1/P2/P3.
4. **Assign** - owner and expected fix date.
5. **Fix** - code, data, documentation, or figure update.
6. **Verify** - rerun the same participant scenario.
7. **Close** - link issue to commit/PR and updated benchmark result.

## 9. Traceability matrix

Use this matrix to make the process auditable later.

| Trace ID | Agent | Stage | Dataset | Requirement / gate | Evidence | Issue ID | Owner | Status | Fix reference |
|---|---|---|---|---|---|---|---|---|---|
| T-001 | A1 | Install | None | G0 PyPI install | install_log.txt | TBD | Dev owner | Open | TBD |
| T-002 | A1 | Hello-world | Toy | G1 first output | quickstart_output/ | TBD | Dev owner | Open | TBD |
| T-003 | A2 | Benchmark | I-10 | G10 benchmark comparison | benchmark_comparison_report.csv | TBD | Benchmark owner | Open | TBD |
| T-004 | A3 | Dashboard | I-395/NVTA | G11 dashboard usability | dashboard_review.md | TBD | Dashboard owner | Open | TBD |
| T-005 | A4 | FD/QVDF | I-405 PeMS | G6/G9 physics and QVDF MAE | fd_validation.csv, qvdf_validation.csv | TBD | Theory owner | Open | TBD |

## 10. AI-agent prompt template

Use this prompt to simulate each participant:

```text
You are an external participant testing the CBI/CPI/QVDF PyPI package for an IEEE Big Data-style competition.
Your persona is: [FIRST-YEAR STUDENT / AI COMPETITOR / DOT ANALYST / TRAFFIC-FLOW RESEARCHER / SOFTWARE DEVELOPER / DASHBOARD USER / RL USER].

Start from a clean environment. Do not assume private paths. Follow only the public README and package documentation.

Your tasks are:
1. Install the package.
2. Run the smallest example.
3. Learn the FD, CBI/CPI, QVDF, benchmark, and dashboard engines.
4. Apply the provided datasets to calibration and diagnosis.
5. Identify confusion, bugs, missing functions, undocumented assumptions, and dashboard issues.
6. Submit a structured feedback package with commands, outputs, screenshots, and issue reports.

Judge the tool by whether it helps you understand congestion mechanisms, not only whether it creates plots.
```

## 11. Weekly operating cadence after PyPI release

| Day | Activity | Output |
|---|---|---|
| Day 1 | PyPI front-door test with A1 and A5 | install and quickstart fixes |
| Day 2 | I-10 benchmark test with A4 | QVDF/theory validation fixes |
| Day 3 | I-405 PeMS test with A2 and A6 | data contract and dashboard fixes |
| Day 4 | I-395/NVTA test with A3 | CBI/CPI ranking fixes |
| Day 5 | RL/digital-twin test with A7 | state/action/reward and physics-gate notes |
| Day 6 | Triage and bug-fix sprint | prioritized backlog and PR list |
| Day 7 | Rerun all failed participant scenarios | release-readiness report |

## 12. Final release-readiness criterion

The package is ready for broader competition use only when:

1. A clean user can install and run the quickstart.
2. A novice can understand the glossary and first example.
3. I-10, I-405, and I-395 benchmark cases reproduce within tolerance.
4. FD/CBI/QVDF outputs include units, assumptions, and physical gates.
5. Dashboards explain congestion mechanisms, not only draw plots.
6. Each serious confusion point has either a code fix, documentation fix, or explicit known limitation.
7. The traceability matrix links every major issue to an evidence file and a fix reference.

**Bottom line:** the PyPI package should become a learning system. AI participants help us discover where the package fails to teach, fails to explain, fails to validate, or fails to support engineering decisions.

---

## Appendix A — Implementation status in this repo (2026-07-08)

The protocol above is the operating standard; this appendix records what is
already instantiated so future waves don't restart from zero.

| Protocol element | Status in repo |
|---|---|
| Personas A1–A7 | Waves run so far: 5-university review panel + 2 competition teams ([reviews/SIMULATED_PANEL_2026-07-08.md](reviews/SIMULATED_PANEL_2026-07-08.md), [reviews/SIMULATED_COMPETITION_USERS_2026-07-08.md](reviews/SIMULATED_COMPETITION_USERS_2026-07-08.md)); RITIS-engineer, INRIX-engineer, and coder-review personas in wave 3 |
| G0 install / G2 dependencies | clean-venv wheel install matrix in [PACKAGE_GUIDE.md](PACKAGE_GUIDE.md) (NumPy 2.4 / pandas 3.0) |
| G1 first output <15 min | `api.verify_installation()` (data-free, ~30 s) + notebook 01 |
| G3 data contract | upfront validator in `api.diagnose` (one message lists all missing columns) |
| G4 units | mph/per-lane guards (median>90 km/h warning; p95>3200 total-flow warning); `speed_units="kmh"`; `load_ieee_v4` |
| G5 observed/imputed mask | `load_ieee_v4` + adapters drop `is_observed==0` |
| G6 FD physics | `fd_summary["fit_ok"]` band + `benchmark_gates` |
| G7/G8 queue + active/passive | episodes frame (`t0/t2/t3_time`, `P_min`, `min_speed_mph`) + stage-6 classes |
| G9 QVDF MAE ≤ 10 mph | hard gate in `benchmark_gates` |
| G10 benchmark comparison | `repro_gates` (25/25) + `benchmark_expected/actual_statistics.csv` |
| G12 feedback loop | [ISSUE_REGISTER.md](ISSUE_REGISTER.md) (master, per-tool) + issue/run log CSVs in [reviews/](reviews/) |
| Traceability matrix (§9) | live instances: `reviews/ai_participant_run_log.csv`, `reviews/ai_participant_issue_log.csv`; blank templates in `reviews/templates/` |
| Weekly cadence (§11) | starts at PyPI release (owner action pending) |

Open protocol gaps: G11 dashboard-usability review is only partially
instantiated (RITIS-persona wave); Stage-2 step 5 "participant-provided
data" has no external instance yet.
