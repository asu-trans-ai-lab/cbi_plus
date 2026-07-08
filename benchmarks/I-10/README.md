# I-10 — CA PeMS sample (San Bernardino Freeway)

Caltrans PeMS speed + measured volume + density for Interstate 10 in
Los Angeles District 7, the El Monte → Pomona segment. Posted 65 mph;
4-5 lanes per direction; heavy commute + truck mix.

## Files

| File | What | Size |
|---|---|---|
| `link_performance.json` | 32 sensors × 31 days × 288 5-min intervals; per-sensor {meta, t0, dt, n, f, s, d} | 5.5 MB |
| `sensor_information.csv` | sensor_id, Fwy, Dir, District, County, Abs_PM, Latitude, Longitude, Length, Type, Lanes, Name | 5 KB |

## Coverage

- **Period**: March 1-31, 2018 (1 month)
- **Sensors**: 32 (16 East + 16 West)
- **Cadence**: 5-minute
- **Postmile range**: 3.6 - 46.1 (~42 miles)
- **Fields**: `f` = flow vph/lane, `s` = speed (km/h despite the `speed_mph` legacy name — converted by the loader), `d` = density veh/km/lane

## How to load

```python
from cbi_pipeline import io_unified
df = io_unified.load_pems(
    path="benchmarks/I-10/link_performance.json",
    representative=False,         # this IS the full subset
)
# Filter to one direction
df = df[df["corridor"] == "10-E"]
```

## Why this dataset matters for teaching

- **Real measured volume**: drives a full S3 FD fit per sensor (R² ~ 0.95
  typical for urban interstates). Compare to the I-17 case where the S3
  fit is structurally trivial because flow was synthesized via S3.
- **Long enough for elasticity**: 31 days × 3 periods × 32 sensors = up to
  2976 (sensor × date × period) cells. Plenty of data for Stage 5b's
  bootstrap CIs to be tight.
- **Mid-strength congestion**: moderate share of days are congested. Expect
  a positive `mu_R2_gap_valid_vs_all` of around +0.10 to +0.20 — the
  structural-bias finding is visible but not dominant.
- **Multi-sensor corridor aggregation**: 16 sensors per direction lets the
  corridor-level Q_n / Q_cp estimates aggregate across distinct bottleneck
  geometries — the shrinkage will be near 0 (data dominates).

## Expected results

With `teaching_cases/case_02_ca_pems_i10.py`:

```
qc_pass_rate            >0.93       PASS
direction_confidence     unknown    UNKNOWN (representative file is per-sensor)
valid_episode_pct       >0.40       PASS
fd_R2 (PeMS)            ~0.95       PASS
mu_R2_gap_valid_vs_all  +0.10..+0.25  PASS
Reliability by period   PM=high, MD=high, AM=high
```

## Source

Caltrans Performance Measurement System (PeMS), District 7.
