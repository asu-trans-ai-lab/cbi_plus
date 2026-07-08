#!/usr/bin/env python3
"""Extract a teaching payload from the CBI/QVDF run for the gui4gmns page.

Reads the corridor outputs (episodes, stage4/5 verification, stage5b aggregate,
quality gates) plus the adapter JSON (raw speed fields), and writes ONE
data.json for the browser teaching lab:

    - two corridor-days (recurring vs event): space-time speed fields
    - CBI episode objects per day (absolute T0/T2/T3, P, v_t2, discharge, mu)
    - hero-bottleneck detail: v(t), q(t), QVDF round-trip td_speed(t)
    - corridor QVDF parameter table + quality gates

Usage:  python tfb_teaching_extract.py [out_json]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CODES = Path(__file__).resolve().parent
OUT_RUN = CODES / "outputs" / "trafficflowbench"
CORR_DIR = OUT_RUN / "210-E"
ADAPTER_JSON = OUT_RUN / "_inputs" / "tfb_I-210E_2026-06-01_2026-06-28.json"

DAY_RECURRING = "2026-06-16"   # stable weekday, class=recurring (manifest)
DAY_EVENT = "2026-06-19"       # highest pct_abnormal in June, class=event
PERIOD_START = {"AM": 6, "MD": 10, "PM": 16}

DEFAULT_OUT = Path("C:/source_codes/0_source_code_new/dynamic_ODME/gui4gmns/"
                   "github_dev/docs/trafficflowbench/cbi_lab/data.json")


def hhmm(day_idx_5min: int) -> str:
    m = day_idx_5min * 5
    return f"{m // 60:02d}:{m % 60:02d}"


def load_fields():
    blob = json.loads(ADAPTER_JSON.read_text())
    t0 = pd.Timestamp(next(iter(blob.values()))["t0"])
    sensors = sorted(blob, key=lambda s: blob[s]["meta"]["milepost_mi"])
    days = {}
    for day in (DAY_RECURRING, DAY_EVENT):
        off = int((pd.Timestamp(day) - t0).days) * 288
        speed, flow = [], []
        for s in sensors:
            sp = blob[s]["s"][off:off + 288]
            fl = blob[s]["f"][off:off + 288]
            speed.append([round(v / 1.609, 1) if v is not None else None for v in sp])  # mph
            flow.append([round(v) if v is not None else None for v in fl])
        days[day] = {"speed_mph": speed, "flow_vphpl": flow}
    meta = [{"sensor": s,
             "milepost": round(blob[s]["meta"]["milepost_mi"], 2),
             "lanes": blob[s]["meta"]["lanes"]} for s in sensors]
    return sensors, meta, days


def episodes_for(v4: pd.DataFrame, day: str, sensors: list) -> list:
    sub = v4[v4["date"] == day]
    out = []
    for _, r in sub.iterrows():
        sid = r["sensor_uid"].replace("pems::", "")
        if sid not in sensors:
            continue
        p0 = PERIOD_START.get(r["period"], 0) * 12
        out.append({
            "sensor": sid, "row": sensors.index(sid), "period": r["period"],
            "t0": hhmm(p0 + int(r["t0_idx"])), "t2": hhmm(p0 + int(r["t2_idx"])),
            "t3": hhmm(p0 + int(r["t3_idx"])),
            "t0i": p0 + int(r["t0_idx"]), "t2i": p0 + int(r["t2_idx"]),
            "t3i": p0 + int(r["t3_idx"]),
            "P_min": round(float(r["P_min"]), 0),
            "v_t2": round(float(r["v_t2_mph"]), 1),
            "v_c": round(float(r["v_c_prior_mph"]), 1),
            "mu": round(float(r["mu_obs_vphpl"]), 0) if np.isfinite(r["mu_obs_vphpl"]) else None,
            "cap": round(float(r["capacity_calibrated_vphpl"]), 0),
            "d0i": p0 + int(r["discharge_start_idx"]) if np.isfinite(r["discharge_start_idx"]) else None,
            "d1i": p0 + int(r["discharge_end_idx"]) if np.isfinite(r["discharge_end_idx"]) else None,
        })
    return out


def qvdf_for(v5: pd.DataFrame, day: str, sensor_uid: str, period: str) -> dict | None:
    sub = v5[(v5["date"] == day) & (v5["sensor_uid"] == sensor_uid) & (v5["period"] == period)]
    if sub.empty:
        return None
    r = sub.iloc[0]
    keys = ["R1_P_obs_min", "R1_V_t2_obs_mph", "R1_D_over_C", "Q_n", "Q_s", "Q_cd",
            "Q_cp", "Q_alpha", "Q_beta", "P_hat_min", "P_err_pct", "vt2_hat_mph",
            "vt2_err_pct", "Q_mu_vphpl", "Q_gamma", "t0_hat_hour", "t3_hat_hour",
            "v_t_MAPE_pct"]
    return {k: (round(float(r[k]), 4) if np.isfinite(r[k]) else None)
            for k in keys if k in r.index}


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sensors, meta, days = load_fields()

    v4 = pd.read_csv(CORR_DIR / "stage4_verification" / "stage4_verification.csv")
    v5 = pd.read_csv(CORR_DIR / "stage5_verification" / "stage5_qvdf_verification.csv")
    gates = json.loads((CORR_DIR / "quality_gates.json").read_text())
    agg_path = CORR_DIR / "stage5b_corridor" / "link_qvdf_corridor.csv"
    agg = pd.read_csv(agg_path) if agg_path.exists() else pd.DataFrame()

    # hero bottleneck: most valid episodes across the window, must appear on both days
    counts = v4.groupby("sensor_uid").size().sort_values(ascending=False)
    hero = None
    for cand in counts.index:
        if (len(v4[(v4.sensor_uid == cand) & (v4.date == DAY_RECURRING)]) and
                len(v4[(v4.sensor_uid == cand) & (v4.date == DAY_EVENT)])):
            hero = cand
            break
    hero = hero or counts.index[0]
    hero_sid = hero.replace("pems::", "")

    payload = {
        "corridor": "I-210 E (Foothill Fwy, LA)",
        "window": "2026-06-01 .. 2026-06-28 (28 days, 82 detectors)",
        "days": {
            DAY_RECURRING: {"label": "recurring weekday", "cls": "recurring"},
            DAY_EVENT: {"label": "event day (highest abnormal % in June)", "cls": "event"},
        },
        "sensors": meta,
        "fields": days,
        "episodes": {d: episodes_for(v4, d, sensors)
                     for d in (DAY_RECURRING, DAY_EVENT)},
        "hero": {
            "sensor": hero_sid,
            "row": sensors.index(hero_sid) if hero_sid in sensors else None,
            "milepost": next((m["milepost"] for m in meta if m["sensor"] == hero_sid), None),
            "episodes": {
                d: {p: qvdf_for(v5, d, hero, p) for p in ("AM", "MD", "PM")}
                for d in (DAY_RECURRING, DAY_EVENT)
            },
        },
        "corridor_qvdf": agg.to_dict("records") if not agg.empty else [],
        "gates": {k: v.get("status") for k, v in gates.items()},
        "stats": {
            "episodes_total": int(len(pd.read_csv(CORR_DIR / "stage2_episodes" / "episodes_per_link_day.csv"))),
            "episodes_valid": int(len(v4)),
            "mu_consistency_median": round(float(v4["mu_consistency"].median()), 3),
            "mu_median_vphpl": round(float(v4["mu_obs_vphpl"].median()), 0),
            "P_err_median_pct": round(float(v5["P_err_pct"].abs().median()), 3),
            "vt2_err_median_pct": round(float(v5["vt2_err_pct"].abs().median()), 3),
            "vt_mape_median_pct": round(float(v5["v_t_MAPE_pct"].median()), 1),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload))
    print(f"wrote {out_path}  ({out_path.stat().st_size/1e3:.0f} KB)")
    print("hero bottleneck:", hero_sid, "| gates:", payload["gates"])
    print("stats:", payload["stats"])


if __name__ == "__main__":
    main()
