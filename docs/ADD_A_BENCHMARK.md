# ADD_A_BENCHMARK — how new benchmark data enters this repo

Seven steps. A benchmark is not "added" until step 7 passes. Total effort for a
typical corridor: ~1 hour plus pipeline runtime.

## 1. Create the folder (self-contained rule)

```
benchmarks/<name>/
    data/                complete dataset, NATIVE format (gz anything big;
                         every tracked file <= 10 MB, or exempt it explicitly
                         in validate_no_private_data.py with a written reason)
    reproduce_<name>.py  regenerates every figure/table from data/ alone —
                         RELATIVE paths only, no machine-specific roots
    README or notes      provenance: source, corridor, YEAR/vintage, license
```
PRIVACY: public data only. Agency-restricted data (NVTA/INRIX raw…) stays
outside; link it in `outputs/DATASETS.md` instead. `validate_no_private_data.py`
must stay clean.

## 2. Vintage-stamp it

Same corridor name ≠ same benchmark (we hold three different I-405s). State
corridor, direction, detector count, date range, and data source in the README
and in `benchmarks/MANIFEST.json`.

## 3. Run + verify by eye

`python reproduce_<name>.py` from the folder. Look at every figure. If you are
reproducing published results, compare against the paper/tool's own numbers
and record agreement (exact / % / correlation — see LESSONS_LEARNED #11 for
cross-generation comparisons).

## 4. Key the reference values into the gates

Add an entry to `REGISTRY` in `cbi_pipeline/repro_gates.py`: the script name,
the expected figure files, and 2–5 keyed statistics with tolerances (exact
values for same-code reproductions; floors for cross-tool agreement). These
numbers are the contract future changes are tested against.

## 5. Data pack

Add a loader block to `scripts/build_data_pack.py` (Parquet + 60-row sample +
GeoJSON if the data has geometry) and rerun it. Schemas land in
`benchmarks/_datapack/DATA_FORMATS.md` automatically.

## 6. Page + hub

Write `benchmarks/<name>/index.html` (copy any existing reproduction page —
same CSS block) and add a card to `benchmarks/index.html`. If it changes the
requirement picture, add a row/card to `DEV_STATUS.html`.

## 7. The gate

```
python -m cbi_pipeline.repro_gates --run      # must end PASS-only
```
Then ship through the workspace rule: commit in `dev/`, `cd ../github`,
`git pull dev master && python validate_no_private_data.py && git push`.

## Checklist (copy into your commit message)

- [ ] data/ complete + native format + provenance + vintage stamped
- [ ] reproduce script runs from the folder, relative paths
- [ ] figures verified by eye vs source-of-truth
- [ ] reference values keyed in repro_gates REGISTRY
- [ ] data pack rebuilt (Parquet/sample/GeoJSON/schema)
- [ ] page + hub card
- [ ] repro_gates --run all PASS · privacy validator clean
