# -*- coding:utf-8 -*-
"""Public testbed + package SELF-DEMONSTRATION.

Ships a small set of corridors as BUNDLED average-weekday profiles (`data/*.csv`, ~1 MB total,
derived + anonymized — no raw INRIX/PeMS). The self-demo runs the whole CBI/QVDF pipeline from those
profiles, regenerates every figure + dashboard, and self-validates the key identification parameters
against a recorded baseline (regression guard) — so a release proves itself with one command.

  python testbed/testbed.py demo         # run bundled corridors + dashboards + validate  (the release check)
  python testbed/testbed.py record        # (re)baseline from the demo outputs (after an INTENDED change)
  python testbed/testbed.py validate       # compare current demo outputs to the baseline (no re-run)
  python testbed/testbed.py dashboard      # render testbed_dashboard.png
"""
import os, sys, json, argparse
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))    # the qvdf_selfdemo package dir
if HERE not in sys.path:
    sys.path.insert(0, HERE)                          # so the flat pipeline modules import
import config as C  # noqa: E402
OUT = C.OUT_ROOT
DATA = os.path.join(HERE, "data")
BASELINE = os.path.join(DATA, "golden_baseline.json")
MANIFEST = json.load(open(os.path.join(DATA, "manifest.json")))
TESTBED = list(MANIFEST)                                    # public corridor names (== demo output dirs)

TOL = dict(f_d=0.10, n=0.10, f_p=0.05, s=0.25, capacity=120.0, uc=3.0, m=0.6,
           step1_DC_P_R2=0.10, step2_P_mag_R2=0.20, P_MAPE_pct=3.0, vt2_MAPE_pct=5.0,
           vt2_within_tol_pct=10.0, PM_delay_pct=4.0)


def register_demo():
    """inject the bundled corridors into the registry as `avgweekday_csv` sources."""
    for pub, m in MANIFEST.items():
        C.CORRIDORS[pub] = dict(name=pub, source="avgweekday_csv",
                                path=os.path.join(DATA, f"{pub}.csv"),
                                free_flow=m["free_flow"], capacity_prior=m["capacity_prior"],
                                wd_mode=m.get("wd_mode", "avg_weekday"),
                                data_mode=m.get("data_mode", "measured"),
                                facility_type=m.get("facility_type"), area_type=m.get("area_type"))
    return list(MANIFEST)


def run_demo():
    from pipeline import run_corridor
    register_demo()
    print(f"self-demo: running {len(TESTBED)} corridors from bundled avg-weekday data ...")
    for k in TESTBED:
        try:
            run_corridor(k)
        except Exception as e:
            import traceback; print(f"  [{k}] FAILED: {e}"); traceback.print_exc()


def _read(key, name):
    p = os.path.join(OUT, key, name)
    return pd.read_csv(p) if os.path.exists(p) and os.path.getsize(p) > 5 else None


def extract_key_params(key):
    d = {}
    fd = _read(key, "Stage0_FD.csv")
    if fd is not None:
        r2 = pd.to_numeric(fd.get("fd_fit_R2"), errors="coerce") if "fd_fit_R2" in fd else None
        d["FD"] = dict(n_links=int(len(fd)), capacity=round(float(fd.capacity.median()), 1),
                       uc=round(float(fd.speed_at_capacity_uc.median()), 1),
                       m=round(float(fd.m.median()), 2),
                       fd_fit_R2=(round(float(r2.median()), 3) if r2 is not None and r2.notna().any() else None))
    t7 = _read(key, "Table7_calibrated.csv"); cq = _read(key, "Quality_calibration.csv")
    d["periods"] = {}
    for per in ["AM", "MD", "PM"]:
        row = {}
        if t7 is not None:
            g = t7[t7.period == per]
            if len(g):
                for k in ("f_d", "n", "f_p", "s"):
                    row[k] = round(float(g[k].median()), 4)
        if cq is not None:
            g = cq[cq.period == per]
            if len(g):
                rr = g.iloc[0]
                for k in ("step1_DC_P_R2", "step2_P_mag_R2", "P_MAPE_pct", "vt2_MAPE_pct"):
                    row[k] = round(float(rr[k]), 3)
                if "vt2_within_tol_pct" in g.columns:
                    row["vt2_within_tol_pct"] = round(float(rr["vt2_within_tol_pct"]), 1)
        if row:
            d["periods"][per] = row
    acc = _read(key, "corridor_accounting.csv")
    if acc is not None:
        pm = acc[acc.period == "PM"]
        if len(pm):
            d["PM_delay_pct"] = round(float(pm.delay_share_pct.iloc[0]), 1)
            d["PM_VMT"] = round(float(pm.VMT_mi.iloc[0]))
    return d


def record():
    base = {"corridors": {}}
    for pub in TESTBED:
        if not os.path.isdir(os.path.join(OUT, pub)):
            print(f"  [skip] {pub} — run `demo` first"); continue
        base["corridors"][pub] = extract_key_params(pub)
        print(f"  recorded {pub}")
    json.dump(base, open(BASELINE, "w"), indent=2)
    print(f"wrote {BASELINE} ({len(base['corridors'])} corridors)")


def _cmp(base, cur):
    issues = []
    for k, bv in base.get("FD", {}).items():
        if bv is None or k == "n_links":
            continue
        cv = cur.get("FD", {}).get(k); tol = TOL.get(k)
        if cv is not None and tol is not None and abs(cv - bv) > tol:
            issues.append((f"FD.{k}", bv, cv, tol))
    for per, br in base.get("periods", {}).items():
        cr = cur.get("periods", {}).get(per, {})
        for k, bv in br.items():
            cv = cr.get(k); tol = TOL.get(k)
            if cv is not None and tol is not None and abs(cv - bv) > tol:
                issues.append((f"{per}.{k}", bv, cv, tol))
    if "PM_delay_pct" in base and "PM_delay_pct" in cur and abs(cur["PM_delay_pct"] - base["PM_delay_pct"]) > TOL["PM_delay_pct"]:
        issues.append(("PM_delay_pct", base["PM_delay_pct"], cur["PM_delay_pct"], TOL["PM_delay_pct"]))
    return issues


def validate(rerun=False):
    if not os.path.exists(BASELINE):
        print("no golden_baseline.json — run `demo` then `record` first"); return 1
    if rerun:
        run_demo()
    base = json.load(open(BASELINE))["corridors"]
    rows, all_issues, n_pass = [], {}, 0
    for pub, b in base.items():
        cur = extract_key_params(pub); issues = _cmp(b, cur)
        n_pass += not issues
        all_issues[pub] = issues
        rows.append([pub, "PASS" if not issues else "DRIFT", len(issues), cur.get("PM_delay_pct", "")])
    rep = pd.DataFrame(rows, columns=["corridor", "status", "n_drift", "PM_delay_%"])
    rep.to_csv(os.path.join(OUT, "validation_report.csv"), index=False)
    print("\n================ TESTBED SELF-VALIDATION ================")
    print(rep.to_string(index=False))
    for pub, iss in all_issues.items():
        for metric, bv, cv, tol in iss:
            print(f"  DRIFT {pub} {metric}: baseline={bv} current={cv} (tol +-{tol})")
    print(f"\n{n_pass}/{len(base)} corridors match the recorded baseline within tolerance.")
    return 0 if n_pass == len(base) else 2


def dashboard():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if not os.path.exists(BASELINE):
        print("run `demo` + `record` first"); return
    b = json.load(open(BASELINE))["corridors"]; pubs = list(b)
    cols = ["capacity", "u_c", "m", "PM f_d", "PM n", "PM f_p", "PM s", "V_t2 gate%", "PM delay%"]
    rows, colors = [], []
    for p in pubs:
        d = b[p]; fd = d.get("FD", {}); pm = d.get("periods", {}).get("PM", {})
        g = pm.get("vt2_within_tol_pct", float("nan"))
        rows.append([fd.get("capacity"), fd.get("uc"), fd.get("m"), pm.get("f_d"), pm.get("n"),
                     pm.get("f_p"), pm.get("s"), g, d.get("PM_delay_pct")])
        colors.append(["#eaffea" if (isinstance(g, (int, float)) and g >= 70) else "#fff3d6"] * len(cols))
    f, ax = plt.subplots(figsize=(13, 0.6 * len(pubs) + 1.4)); ax.axis("off")
    t = ax.table(cellText=[[("" if v is None else v) for v in r] for r in rows], rowLabels=pubs,
                 colLabels=cols, cellColours=colors, loc="center", cellLoc="center")
    t.auto_set_font_size(False); t.set_fontsize(8); t.scale(1, 1.4)
    ax.set_title("CBI/QVDF public testbed (self-demo from bundled avg-weekday data)\n"
                 "recorded key identification parameters — green = V_t2 gate PASS (>=70% links <10 mph)", fontsize=11)
    f.tight_layout(); p = os.path.join(OUT, "testbed_dashboard.png")
    f.savefig(p, dpi=140); plt.close(f); print("wrote", p)


def demo():
    run_demo()
    import dashboard as D
    from run import _cross_corridor_summary
    D.build_dashboard(TESTBED); _cross_corridor_summary(TESTBED)
    if os.path.exists(BASELINE):
        dashboard(); return validate(rerun=False)
    else:
        record(); dashboard()
        print("(first run — baseline recorded; re-run `demo` to self-validate)"); return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="qvdf-selfdemo",
                                 description="CBI/QVDF self-demonstration from bundled avg-weekday data")
    ap.add_argument("cmd", nargs="?", default="demo",
                    choices=["demo", "record", "validate", "dashboard"])
    a = ap.parse_args(argv)
    if a.cmd == "demo":
        return demo()
    if a.cmd == "record":
        record(); return 0
    if a.cmd == "dashboard":
        dashboard(); return 0
    return validate(rerun=False)


if __name__ == "__main__":
    sys.exit(main() or 0)
