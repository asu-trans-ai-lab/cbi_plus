# Teaching notebooks — the hands-on ladder

Executed notebooks (outputs visible right on GitHub — no install needed to
*read* them). To *run* them: `pip install cbi-plus` or clone the repo, then
open in Jupyter. Notebook 01 needs **no data at all**; the rest use only
in-repo datasets.

| # | notebook | what you learn | data |
|---|---|---|---|
| 01 | [Getting started](01_getting_started.ipynb) | install check, simulate a corridor, diagnose it, read a CBI ranking | none (simulated) |
| 02 | [Queue anatomy](02_queue_anatomy_T0_T2_T3.ipynb) | T0/T2/T3, duration P, worst speed v_t2, discharge rate μ, capacity drop | simulated |
| 03 | [Fundamental diagram](03_fundamental_diagram.ipynb) | robust FD fitting, model choice vs capacity, why Huber | fd_16models (real) |
| 04 | [QVDF on real I-10](04_qvdf_real_I10.ipynb) | D/C in HOURS, duration + worst-speed power laws, planning bridge | Caltrans PeMS 2018 (in-repo) |
| 05 | [CBI ranking on IEEE v4](05_cbi_ranking_ieee_v4.ipynb) | active vs passive vs spillback classes, the investment argument, v4 format lessons | IEEE v4 sample (in-repo) |

Suggested pace: 01+02 in the first sitting (~40 min), 03–05 one per sitting.
Then the deeper ladder: [docs/teaching/README.md](../docs/teaching/README.md)
(Excel hand-calculations), [docs/GLOSSARY.md](../docs/GLOSSARY.md), and the
[benchmark reproductions](../benchmarks/index.html).

Regeneration note: these notebooks are executed before every ship; if you
re-run them yourself, results are deterministic (seeded) except for minor
matplotlib layout differences.
