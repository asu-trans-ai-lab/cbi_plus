# I-405 — CA PeMS sample (San Diego Freeway)

Caltrans PeMS speed + measured volume + density for Interstate 405 in
Los Angeles District 7, the Long Beach → Sherman Oaks segment. Posted 65 mph;
4-6 lanes per direction; **chronic** weekday congestion in both AM and PM.

## Files

| File | What | Size |
|---|---|---|
| `link_performance.json` | 29 sensors × 31 days × 288 5-min intervals; per-sensor {meta, t0, dt, n, f, s, d} | 5.0 MB |
| `sensor_information.csv` | sensor_id, Fwy, Dir, District, County, Abs_PM, Latitude, Longitude, Length, Type, Lanes, Name | 5 KB |

## Coverage

- **Period**: March 1-31, 2018 (1 month)
- **Sensors**: 29 (9 North + 20 South)
- **Cadence**: 5-minute
- **Postmile range**: 26.7 - 72.1 (~45 miles)
- **Fields**: same as I-10

## How to load

```python
from cbi_pipeline import io_unified
df = io_unified.load_pems(
    path="datasets/I-405/link_performance.json",
    representative=False,
)
df = df[df["corridor"] == "405-S"]
```

## Why this dataset matters for teaching

- **Chronic congestion**: I-405-S is one of the most congested corridors in
  the United States. Nearly every weekday in March 2018 has multi-hour
  congestion events.
- **Informative non-finding**: when ~90% of days are congested, the
  `all_days` and `valid_only` mu-R² samples are nearly identical, so the
  `mu_R2_gap` gate often FAILS. **This is the finding, not a bug** — it
  tells you the structural-bias correction is irrelevant for this corridor
  because there are no uncongested days to contaminate the estimate.
- **Long P episodes**: many days have P > 4 hours. Excellent stress test for
  the fourth-order queue profile in Stage 5 verification — expect
  `v(t) MAPE > 100%` on the longest episodes because the symmetric queue
  shape assumption is structurally too rigid.
- **Stage 2b outlier rule firings**: high-volume corridors trigger real
  outliers (incident days, sensor mismatches near interchanges). Compare
  to I-17 (0 outliers) to see the spectrum.

## Expected results

With `teaching_cases/case_03_ca_pems_i405.py`:

```
qc_pass_rate            >0.90        PASS
direction_confidence     unknown     UNKNOWN
valid_episode_pct       >0.70        PASS  (chronic congestion)
fd_R2 (PeMS)            ~0.93        PASS
mu_R2_gap_valid_vs_all   small or negative   FAIL  <- informative
qvdf_n_fitted            >=5         PASS
```

## Source

Caltrans Performance Measurement System (PeMS), District 7.
