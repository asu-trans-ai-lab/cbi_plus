# PACKAGE_GUIDE — cbi-plus as a pip-installable package

The pipeline is a Python package (`cbi-plus` on PyPI once published; the
import name is `cbi_pipeline`). Everything a notebook, script, or downstream
tool needs sits behind one stable facade: **`cbi_pipeline.api`**.

```bash
pip install cbi-plus            # from PyPI (after first upload)
pip install -e .                # or from a repo checkout
python -c "from cbi_pipeline import api; api.verify_installation()"
```

`verify_installation()` is an install/CI **smoke test** (not scientific evidence) and needs **no data files**: it simulates corridors across three seeds
with one AM active bottleneck, runs the full QC → episodes → FD → QVDF →
CBI-ranking chain, and checks that the planted bottleneck is ranked #1 in
every seed.

## The 60-second tour

```python
from cbi_pipeline import api

df = api.simulate_corridor(days=5, seed=1)   # or api.load_pems(...) / api.load_inrix_folder(...)
out = api.diagnose(df)                       # QC -> episodes -> FD -> QVDF -> ranking

out["ranking"].head()                        # CBI scores + bottleneck classes
out["episodes"][["sensor_uid", "period", "t0_index", "P_min", "min_speed_mph"]]
out["fd_summary"]                            # per-sensor capacity + v_f
out["qvdf"]["params"]                        # QVDF elasticities per (sensor, period)
```

## Input contract (the one format requirement)

`diagnose()` and `run_qc()` accept a **long-format frame** — one row per
sensor per 5-minute bin:

| column | type | required | notes |
|---|---|---|---|
| `sensor_uid` | str | yes | detector / TMC id |
| `datetime` | datetime64 | yes | naive local time, 5-min cadence |
| `speed_mph` | float | yes | mph (convert km/h feeds: ÷1.609) |
| `flow_vph` | float | no | **PER LANE** veh/h/ln (physically <= ~2600; p95 above 3200 triggers a warning — you passed totals) |
| `density_vpm` | float | no | per-lane veh/mi/ln; **derived as flow/speed automatically** when absent (FD stage needs it) |
| `road_order` | int | yes | upstream → downstream ordering (spatial QC + wave checks) |
| `corridor`, `direction`, `lanes`, `length_mi`, `has_volume`, `source_format` | — | recommended | carried into outputs |

Package-wide unit conventions (see `docs/CONTRACTS.md`): speed **mph**,
flow **veh/h**, density **veh/mi/ln**, **D/C in HOURS** — never a plain
ratio. Imputed cells (`is_observed == 0` in TFB/IEEE releases) must be
dropped before calibration — imputation is a prior, not a measurement.

## What `diagnose()` returns (the frame schemas)

| key | type | key columns |
|---|---|---|
| `qc` | DataFrame | input + `speed_mph_clean`, `qc_pass` |
| `episodes` | DataFrame | `sensor_uid, date, period, t0_index/t2_index/t3_index` (period-relative 5-min bins) + `t0_time/t2_time/t3_time` (clock), `P_min`, `min_speed_mph` (= v_t2), `regime`, `is_valid_for_mu` |
| `fd_summary` | DataFrame or None | `sensor_uid, capacity_vphpl, v_f_mph, r_squared, fit_ok` (physics flag — check it!) |
| `qvdf` | dict or None | `params` (per sensor-period elasticities), `predictions`, `n_fitted` (0 when the window is too short, e.g. 3-day samples) |
| `ranking` | DataFrame | `corridor, sensor_uid, period, CBI_score, bottleneck_class, rank_in_corridor` |

Input rules enforced up front: missing required columns raise ONE error
listing them all; recommended columns get defaults; tz-aware datetimes are
rejected (AM/MD/PM are local clock windows); `speed_units="kmh"` converts
km/h feeds; suspicious magnitudes (km/h-as-mph, total-as-per-lane flow)
raise loud warnings.

## Public API surface (`cbi_pipeline.api`)

| call | what it does |
|---|---|
| `simulate_corridor(...)` | synthetic corridor with a planted AM bottleneck — queue balance, capacity drop, conservation-correct downstream metering (teaching / CI / install check) |
| `diagnose(df, ...)` | one-call QC → episodes → FD → QVDF → CBI ranking on an in-memory frame |
| `run_corridor(...)` | the full disk-writing workflow (stages 1–6, figures, gates) |
| `load_pems / load_inrix / load_inrix_folder / load_sensor_timeseries` | feed loaders |
| `load_ieee_v4(states_csv, chain_csv=None)` | IEEE v4 loader: km/h→mph, total→per-lane flow (data-derived effective lanes), `is_observed` filter, chain-order road_order (S/W corridors!) |
| `fd_models()` | model names accepted by `fit_fd_huber` (lookup is case-insensitive) |
| `run_qc / run_episodes / run_fd / run_qvdf / run_ranking` | individual stages |
| `fit_fd_huber / bootstrap_fd` | FD fitting — returns derived `capacity_vphpl`/`k_c_vpm`/`v_c_mph` too; `fd_model_zoo` is a *module* (registry via `fd_models()`) |
| `fit_qvdf_P / fit_qvdf_v_t2 / fit_qvdf_v_avg / predict_qvdf` | QVDF pieces |
| `classify_day / discharge_window` | the per-day queue primitives (T0/T2/T3, μ window) |
| `verify_installation()` | data-free self-test |
| `version()` | installed version |

## Console commands (installed with the package)

```bash
cbi-corridor --corridor 10-E --source pems --pems-path <link_performance.json>
cbi-gates    <run_dir>        # hard physics gates on a finished run
cbi-repro                     # reproduction gates (needs the repo's benchmarks/)
cbi-discover <root>           # inventory CBI-compatible datasets under a tree
```

`cbi-repro` verifies benchmark reproductions and therefore needs a repo
checkout; the other three work anywhere.

## Verified install matrix (2026-07-08)

Windows note: create the venv at a SHORT path (MAX_PATH breaks deep installs).
Wheel built with `python -m build`, installed into a **clean venv**
(Python 3.11, pandas 3.0.3, NumPy 2.4 — newer than the dev machine):

| dataset family | result |
|---|---|
| simulated corridor (data-free) | PASS — planted bottleneck ranked #1 |
| speed-only feed (synthesized volume) | PASS — 90 episodes, 3 ranked |
| FD fit on `fd_16models` input | PASS — S3 capacity 1642 vphpl, R² 0.896 |
| PeMS I-10 2018 full workflow | PASS — stages 1–6 + gates on 3 sensors |
| IEEE v4 sample I-405N (km/h + `is_observed` mask) | PASS — 634 episodes, 27 ranked |

The clean-venv pass caught a real bug: `np.trapz` was removed in NumPy 2.x
and the old compat shim evaluated its fallback eagerly — fixed in
`stage5_qvdf.fit_shape_model`. This is why the install test runs against
*newer* dependencies than the dev machine.

## Publishing to PyPI (owner action)

```bash
python -m build                      # dist/cbi_plus-X.Y.Z-py3-none-any.whl + .tar.gz
python -m twine upload dist/*        # needs the lab's PyPI account token
```

Versioning: bump `[project] version` in `pyproject.toml`; keep the repo tag
and the wheel version identical. The wheel ships **code only** (plus the
dashboard template) — benchmarks and datasets stay in the repo, which is why
`cbi-repro` needs a checkout.
