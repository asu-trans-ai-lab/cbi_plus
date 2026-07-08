# PLAYBOOK — onboard a corridor · add a dataset (incl. parquet)

*From the independent review (Jinxi Wu, ASU, 2026-07-08): the pieces
existed but there was no single "add a dataset / onboard a corridor" page.
This is it. Pair with [ADD_VOCABULARY.md](ADD_VOCABULARY.md).*

## 0. Make imports work from anywhere (do this once)

The documented commands assume you run from `dev/`. To write your own
scripts in any folder:

```bash
pip install -e .        # from dev/ — now `from cbi_pipeline import api` works everywhere
```

Without this you'll hit `ModuleNotFoundError: cbi_pipeline` outside `dev/`.

## 1. The reference known-good run: I-405 QVDF (start here)

The flagship reproduction is the QVDF paper **I-405 case study**. Its
folder is historically named `qvdf_paper_casestudy2` (Case Study 2 in the
paper == I-405; Case Study 1 == I-10 in `qvdf_paper_i10`):

```bash
cd benchmarks/qvdf_paper_casestudy2 && python reproduce_casestudy2.py
# reproduces coefficients C=1662, n=1.046, f_d=1.124, f_p=0.219, s=0.939;
# self-consistency |est_P - workbook est_P| median = 0.0000 h; Figs 19-23
```

Diff any new corridor's behavior against this run — it's the "does my
pipeline still work" anchor.

## 2. Add a dataset — write the sidecar FIRST

The single best habit in this repo: before loading anything, write a
`dataset_meta.json` next to the data (schema:
[../schemas/dataset_meta.schema.json](../schemas/dataset_meta.schema.json),
Contract 7). It declares units so a loader never guesses:

```json
{
  "meta_version": 1,
  "name": "my_corridor_2026",
  "units": {"speed": "kmh", "flow_scope": "total_all_lanes"},
  "loader": "parquet",
  "files": {"states": "detector_states.parquet"},
  "columns_map": {"sensor_uid": "station_id", "datetime": "timestamp",
                  "speed": "speed", "flow": "flow", "milepost": "milepost",
                  "is_observed": "is_observed"}
}
```

Then one line loads it with units applied from the declaration:

```python
from cbi_pipeline import api
df  = api.load_dataset("path/to/dataset_folder")   # or a specific loader below
out = api.diagnose(df)
```

## 3. The loader decision tree

| your file | loader | one-liner |
|---|---|---|
| PeMS compact JSON (+ sensor_information.csv) | `pems_compact_json` | `api.load_pems(path=".../link_performance.json")` |
| IEEE v4 detector-states CSV | `ieee_v4` | `api.load_ieee_v4(".../train_...csv", chain_csv=...)` |
| **Parquet detector states** (TFB-shaped or your own) | `parquet` | `api.load_parquet(".../states.parquet", speed_units="kmh", flow_scope="total_all_lanes", columns={...})` |
| INRIX RITIS export folder (Reading*.csv + TMC_Identification.csv) | `inrix_folder` | `api.load_inrix_folder(".../folder", min_confidence=30)` |
| a plain contract CSV already in package columns | `contract_csv` | `api.load_dataset(folder)` |

### Parquet specifics (new in this release)

`api.load_parquet` handles the two traps every parquet feed hits — the
same logic `tfb_adapter.py` had, now behind the public API:

- **`is_observed`**: stations observed < 60% are dropped; imputed cells on
  the rest are blanked (a prior never calibrates). Tune with
  `min_observed_frac`.
- **units**: `speed_units="kmh"` → mph; `flow_scope="total_all_lanes"` →
  per-lane via data-derived effective lanes (p99 flow / 1900).
- **column map**: pass `columns={"sensor_uid": "...", "datetime": "...", ...}`
  when your parquet uses different names; defaults match the TFB release.

Full-corridor batch runs against the whole TrafficFlowBench release still
use `tfb_adapter.py` (it also builds the GMNS lane table and sensor
information); `api.load_parquet` is the direct path for a single parquet
file into `diagnose`.

**Provenance caveat**: don't persist a diagnosed frame to parquet expecting
`df.attrs` (e.g. the synthesized-volume prior) to survive — parquet drops
`attrs`. The `s3_prior_label` / `flow_synthetic` columns survive; the attr
does not.

## 4. Onboard a corridor — the run + the gates

```bash
# measured-volume (PeMS): real FD fit
python -m cbi_pipeline.corridor_workflow --corridor 405-S --source pems \
    --pems-path benchmarks/I-405/link_performance.json

# speed-only (INRIX TMC): volume synthesized via the S3 prior
python -m cbi_pipeline.corridor_workflow --corridor I-17 --source inrix \
    --inrix-folder <folder> --s3-prior az_tmc_i17 --rederive-kc-and-m
```

Then read `quality_gates.json`. **Expected FAILs are normal and
documented** — e.g. `benchmarks/I-405/README.md` pre-declares the
`mu_R2_gap` gate will FAIL as an *informative non-finding* (chronic
congestion → no clean discharge days). Check each benchmark README's
expected-outcomes note before treating a FAIL as a problem.

## 5. Then the vocabulary + the Reader loop

Once a corridor is diagnosed: `api.build_issue_graph(out)` →
`api.planner_review(..., reviewer="your name")` → `api.approved_issues`.
Add new congestion/issue words via [ADD_VOCABULARY.md](ADD_VOCABULARY.md).
Gather corroborating web/agency evidence via the
[RAG Evidence Compiler](RAG_EVIDENCE_COMPILER.md).
