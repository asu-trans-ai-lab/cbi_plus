# IEEE TrafficFlowBench v4 — corridor samples (all 4 corridors)

3 weekday extracts per corridor + the complete network/chain_fd tables +
format heads for test/submission. Full release: set `IEEE_V4_ROOT` and use
`ieee_v4_adapter.py <CORR> --run`. Evaluation focus (non-path, non-OD):
physical gate first, then S_state = 0.40*all + 0.60*congested cells.

Engines callable on these samples: see docs/ENGINE_SHOWCASE.md.

## Note on the 3-day sample extracts

The shipped samples contain **0% imputed cells** (`is_observed == 0` never
occurs) — good for quick starts, but it means you cannot rehearse the
imputation pitfall here; the full release does contain imputed cells, and
`api.load_ieee_v4` / the adapters drop them. QVDF calibration needs more
days than these samples provide (`qvdf["n_fitted"]` will be 0 — expected).
