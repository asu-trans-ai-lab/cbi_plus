# Releasing `cbi-plus` to PyPI (automated)

Publishing is automated via GitHub Actions using **PyPI Trusted Publishing (OIDC)** — no API token
or secret is stored anywhere. A published GitHub Release builds and uploads the package.

## One-time setup (do this once)

### 1. PyPI project + trusted publisher
1. Create/sign in to a PyPI account (https://pypi.org) with 2FA on.
2. Go to **https://pypi.org/manage/account/publishing/** → *Add a pending publisher* and enter:
   - **PyPI Project Name:** `cbi-plus`
   - **Owner:** `asu-trans-ai-lab`
   - **Repository name:** `cbi_plus`
   - **Workflow name:** `publish-pypi.yml`
   - **Environment name:** `pypi`
   (A "pending" publisher lets the very first upload create the project — no manual first upload.)

### 2. GitHub environment
In the repo → **Settings ▸ Environments ▸ New environment** → name it **`pypi`**.
(Optionally add required reviewers so a human approves each publish.)

### 3. (Recommended) TestPyPI dry-run
Repeat step 1 on **https://test.pypi.org** if you want to rehearse; the `ci.yml` workflow already
builds + `twine check`s on every push so releases don't fail at build time.

## Cutting a release (every time)
```bash
# 1. bump the version in pyproject.toml  (e.g. 2.11.0 -> 2.11.1)
# 2. ship dev -> github (per WORKSPACE.md) and push
cd cbi_plus/github
git pull dev master
python validate_no_private_data.py        # must print "clean"
git push origin master
git tag v2.11.1 && git push origin v2.11.1
# 3. on GitHub: Releases ▸ Draft a new release ▸ choose tag v2.11.1 ▸ Publish
#    -> the "Publish cbi-plus to PyPI" workflow runs and uploads to PyPI.
```
Or trigger manually: **Actions ▸ Publish cbi-plus to PyPI ▸ Run workflow**.

After it succeeds: `pip install cbi-plus`.

## What the workflows do
- **`.github/workflows/ci.yml`** — on every push/PR, builds the sdist+wheel on Python 3.10/3.11/3.12,
  runs `twine check`, installs the wheel, imports `cbi_pipeline` + `qvdf_selfdemo`, and runs the
  **self-demo** (`qvdf-selfdemo demo`).
- **`.github/workflows/selfdemo.yml`** — runs the CBI/QVDF pipeline on the bundled ~1.2 MB
  average-weekday testbed (`qvdf_selfdemo/data/`), regenerates the dashboards, and **self-validates**
  the key identification parameters against `qvdf_selfdemo/data/golden_baseline.json` — **fails the
  build on drift** and uploads the dashboards as artifacts. This is the release regression gate.
- **`.github/workflows/publish-pypi.yml`** — on a published Release (or manual dispatch), builds and
  publishes to PyPI via the `pypi` environment with OIDC trusted publishing.

## Self-demonstration (ships with the package)
```
pip install cbi-plus
qvdf-selfdemo demo        # runs the pipeline from bundled data -> dashboards -> self-validation (7/7)
```
Updating the baseline after an intended calibration change: `qvdf-selfdemo record` (writes
`qvdf_selfdemo/data/golden_baseline.json`), commit it with the change.

## Local build check
```bash
cd cbi_plus/github
python -m build && python -m twine check dist/*
```
(Verified: `cbi_plus-2.11.0` builds and passes `twine check`.)
