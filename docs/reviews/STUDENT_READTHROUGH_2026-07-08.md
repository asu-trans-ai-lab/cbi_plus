# Simulated first-year-student read-through — full report (2026-07-08)

*Method: an independent AI agent role-played a first-year transportation MS
student with basic Python and NO traffic-flow-theory background, reading the
six teaching documents in order and verifying every path and command against
the actual repo tree. This report drove the fixes shipped the same day
(GLOSSARY.md, working quickstart, learning ladder, path corrections).
Kept verbatim as the template for future read-through audits — rerun one
after every major doc change.*

---

**Verdict up front: the material is unusually well-audited science with a
broken front door.** Both commands in the README's "Install / run" section
fail on a fresh clone, the glossary a beginner needs is hidden at the end of
document 2, and the paper's coefficient names (f_d, n, f_p, s) are never
mapped to the pipeline's names (Q_cd, Q_n, Q_cp, Q_s).

## 1. Where I got lost (highlights per document)

**README.md** — μ used before its gloss; no explanation of why there is no
T1; C and v_c undefined at first use; the four QVDF symbols dropped with zero
gloss; **S3 never expanded in any of the six documents** (reads like a
collision with "Stage 3"); "FIXED-layout" reads as a typo; D/C undefined
until doc 2's pitfall 5 — and its "in hours" definition contradicts the word
"ratio" (the single most confusing unit convention in the corpus, introduced
as an aside); CPI never expanded; **neither run command is runnable from a
fresh clone**; the pip list omitted scipy (ImportError for literal readers).

**TFB_CBI_GUIDE.md** — λ, N, Q never defined; stale `clean_handoff_v2` run
locations (a cbi_plus cloner does not have that folder); `t3_index == 47`
with no sentence explaining periods are 48/72 five-minute bins;
`mu_consistency` used undefined; steps "A–G" never enumerated; MDPM coined
on the spot; units contradiction (cheat sheet said P [min], everything else
uses hours); **the cheat sheet — the best 15 lines in the corpus — was the
LAST section of document 2** when it should be the first thing a learner sees.

**STAGE_CHAIN.md** — the stage-6 box is drawn between stages 2 and 3, so a
first read suggests the order 2→6→3 (one caption fixes it); a phantom
"DEV_STATUS card" reference; workbook sheet names cited one document before
the sheet→stage map explains them.

**teaching/README.md** — Eq. 25/27 and Table 8 cited before the paper enters
the learner's path; **the f_d/n/f_p/s ↔ Q_cd/Q_n/Q_cp/Q_s mapping is never
stated anywhere — the load-bearing missing sentence of the whole curriculum.**

**Benchmark pages** — the Case-Study-2 hub card lands on a page titled
"I-10 Phoenix" with no cue to scroll; QDF unexpanded; γ formula uses L and
u_c undefined at point of use; D/C values like 2.83 look insane without an
"(h)" on every table. *Positive: the best-cited artifact in the corpus —
full citation, provenance, per-statistic tolerances; trusted immediately.*

**ENGINE_SHOWCASE.md** — S_state and the physical gate dropped without a
referent; v_cut is v_c under a third name; "corridor contract" never linked;
"v4" versioning never introduced.

## 2. Broken trails (verified against the tree)

1. README `--corridor 5-N --source pems` — falls back to a data path that
   does not exist in this repo; no 5-N dataset ships anywhere. Working form
   was buried in CLOSEOUT.md (`10-E` + explicit `--pems-path`).
2. `tfb_adapter.py` — requires the external TFB release via TFB_DATA_ROOT;
   docs never said so; fallback was a hard-coded personal path.
3. TFB guide's run/output locations pointed at the *other repo's* copy.
4. cbi_lab companion path missing the `github_dev/` segment.
5. `teaching_cases/case_01` — dataset path `dev/datasets/I-17` does not
   exist (data is under `additional/benchmark_datasets/datasets/I-17`);
   README said "from cbi_pipeline_package/", a directory that exists nowhere.
6. `benchmarks/I-10/README.md` load snippet used a nonexistent root path.
7. ENGINE_SHOWCASE cited "DATASETS.md" without its `outputs/` location.
8. CS2 hub card → page titled I-10 (no anchor, no own landing).
9. STAGE_CHAIN's "DEV_STATUS card" — artifact absent from the repo.
10. **What DID check out:** every pipeline module, all five benchmark
    reproductions' data/scripts/figures, both Excel workbooks, the gates,
    the data pack — "the benchmark layer is solid; only the entry-path
    commands are broken."

## 3. Missing rungs — there was no hello world

First README command failed on missing data; first working command took ~10
minutes on 82 sensors. Proposed ladder (now in the README):
repro_gates verify (~5 s) → one-sensor-day plot + by-hand T0/T2/T3 in the
Excel sheets → `reproduce_qvdf_paper.py` (the true hello world: in-repo data,
~2 min, diffable against published values) → teaching case 02 → only then
the TFB adapter.

## 4. Recommended learning paths

**30 min:** README top → GLOSSARY → STAGE_CHAIN → the four figures of the
i10 reproduction page (Fig 8 FD, Fig 10 D/C→P, Fig 11 P→speed drop, Fig 14
reconstructed v(t)) — "those four figures ARE the method."
**2 h:** + hand T0/T2/T3 exercise, hello-world reproduction, outputs-reading
sections of the guide.
**1 day:** + pip install -e ., teaching cases 02–04 with panel inspection,
repro_gates, FIXES log, ENGINE_SHOWCASE + one more reproduction page.

## 5. Quiz questions (30, five per document)

(Kept in the original agent output — examples:)
- Why is μ/C typically *below* 1 for an active bottleneck?
- An episode has `t3_index == 47` in the AM period — what do you conclude?
- D/C = 4.9 — why may this "ratio" exceed 1, and what unit is it really in?
- At the hero bottleneck μ/C is 0.87 on a recurring day and 0.86 on an event
  day while P doubles — what does that say about capacity drop vs demand?
- Which pipeline stage has no Excel twin (new in v2)?

## 6. Top-10 fix list — ALL APPLIED 2026-07-08

1. README quickstart → commands that run from a clone (+ scipy / `pip install -e .`)
2. TFB commands gated behind TFB_DATA_ROOT with acquisition note
3. Cheat sheet promoted to docs/GLOSSARY.md + missing terms (S3, C, D/C-hours, MDPM, CPI, QDF, γ, no-T1)
4. The f_d/n/f_p/s ↔ Q_cd/Q_n/Q_cp/Q_s two-dialect table (in the glossary)
5. clean_handoff ghosts purged from guide + teaching cases
6. First-30-minutes learning ladder in the README
7. Small path lies fixed (I-10 README, showcase, i10 page, cbi_lab path)
8. Case-Study-2 landing page added
9. Period-bin arithmetic + mu_consistency definition added to the guide
10. STAGE_CHAIN caption + phantom reference fixed

**Structural observation kept for the record:** "the verification culture
(keyed statistics, tolerance columns, repro_gates, the fixes log with root
causes) is the best teaching asset in the repo — it models how traffic
engineering *should* be done. The fixes above are all about the on-ramp,
not the engine."
