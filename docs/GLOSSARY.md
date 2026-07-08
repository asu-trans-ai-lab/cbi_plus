# GLOSSARY — read this first (5 minutes)

```
T0 / T2 / T3   onset / worst point / clearance of a congestion episode.
               (There is no T1: the paper family reserves T1 for an
               intermediate arrival-curve breakpoint that the pipeline's
               scan does not need — T0, T2, T3 are what data identifies.)
P              congestion duration = T3 - T0                      [hours]
v_c (= v_cut)  speed at capacity — the congested/uncongested threshold [mph]
v_t2           the lowest observed speed, reached at T2           [mph]
C              capacity: max sustainable per-lane flow            [veh/h/lane]
mu             discharge rate: median flow while the queue drains (T2->T3)
mu/C           the CAPACITY DROP: an active bottleneck serves below its own
               capacity, typically 0.85-0.95.
D              accumulated flow over the episode, used as a DEMAND    [veh/lane]
               PROXY. Honest caveat: a bottleneck detector measures
               departures (throughput ~= mu), not arrivals — true
               oversaturated demand is unobservable at the bottleneck
               itself (it needs an upstream arrival curve). Treat D
               and D/C as model-derived, not measured.
D/C            demand-to-capacity ratio. UNITS ARE HOURS (per-lane vehicles
               divided by per-lane hourly capacity) — that is why a "ratio"
               of 4.9 is normal: it means ~4.9 hours of work at capacity.
S3             the S-shaped 3-parameter speed-density model (Cheng, Liu,
               Lin & Zhou 2021) — the production fundamental diagram.
               No relation to "Stage 3" (which happens to fit it).
FD             fundamental diagram: the flow-speed-density relation.
lambda / N / Q arrival rate / cumulative count / queue length in the
               cumulative-curve (fluid queue) picture.
QDF            queued demand factor = period volume / episode inflow demand.
MDPM           the merged MD+PM episode label when one queue crosses 16:00.
CBI            Congestion Bottleneck Identification — the ranking
               deliverable (stage 6). (You may see "CPI" in older notes and
               transcripts: it is a historical typo for CBI. One tool, one name.)
gamma          QVDF curvature of the fourth-order queue; in
               gamma = 64*mu*(L/u_c)*f_p*P^(s-4), L = link length [mi] and
               u_c = speed at capacity.
```

## The two dialects — paper vs pipeline (same quantities)

| paper / workbooks | pipeline (stage 5) | meaning |
|---|---|---|
| f_d | Q_cd | duration scale: P = f_d*(D/C)^n |
| n   | Q_n  | oversaturation-to-duration elasticity |
| f_p | Q_cp | speed-reduction scale: v_c/v_t2 - 1 = f_p*P^s |
| s   | Q_s  | duration-to-speed-reduction elasticity |

Everything in `docs/teaching/`, the paper reproductions, and the Excel
workbooks speaks the left column; `stage5_*` code and its CSVs speak the
right column. They are the same four numbers.
