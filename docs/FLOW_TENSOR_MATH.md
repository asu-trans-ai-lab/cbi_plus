# Flow-Through-Tensor for corridor state — the math bridge between the
# traffic-flow engines and the AI zone (sample write-up)

*Companion to the FTT manuscript (flow_through_tensor.tex) and the
computational-graph TSE line (engines/pinn_tse). This note adapts the FTT
view to what cbi_plus measures — corridor state — and states precisely what
we do **not** do: no dynamic OD estimation. OD/path objects appear only as
fixed, given data used for informational consistency checks (matching the
v4 evaluation, where OD-consistency carries weight 0). The question here is
narrower and testable: **is the tensor structure of corridor state useful?***

---

## 1. Objects — everything the pipeline touches is a tensor

**The state tensor.** For a corridor with S detectors (sorted by milepost —
the corridor contract), T time-of-day bins, and D days,

$$\mathcal{X} \in \mathbb{R}^{S \times T \times D}, \qquad
  \mathcal{X}_{s,t,d} = v \;(\text{speed}), \text{ with siblings }
  \mathcal{Q} (\text{flow}), \mathcal{K} (\text{density}).$$

Additional modes extend the same object without new machinery: lanes
(S×T×D×L, the tensor-handoff cube) or user class. The observation mask
$\Omega \in \{0,1\}^{S\times T\times D}$ marks measured cells
(`is_observed`); everything unmeasured is a *prediction target, never data*.

**The network operators (fixed, given).** Let $A \in \{0,1\}^{S \times E}$
map stations to links, $\Delta \in \{0,1\}^{E \times P}$ be link–path
incidence, and $d \in \mathbb{R}^{P}$ fixed path flows from a **given** OD
table (e.g. the benchmark's `base_od`). The FTT chain

$$q \;=\; \Delta\, d, \qquad
  \hat{\mathcal{Q}}_{\cdot,t,d} \;=\; A^{\!\top} q \cdot \tau(t)$$

is used here **forward only** — a linear contraction projecting given demand
onto links (with a fixed time profile $\tau$). We never invert it: solving
for $d$ from $\mathcal{Q}$ is dynamic ODME, which is out of scope by design.
Its only role is the *informational residual* of §4.

**The physics maps (elementwise, differentiable).** The FD
$v = \Phi_{S3}(k;\,v_f, k_c, m)$, the QVDF chain
$P = f_d (D/C)^{n}$, $v_{t2} = v_c/(1 + f_p P^{s})$, and the deficit map
$u = \max(0, v_c - v)$ are scalar maps applied cellwise to tensor slices.

## 2. The computational-graph view

Nodes are tensors; edges are either **contractions** (the linear network
operators $A, \Delta$) or **elementwise physics maps** ($\Phi_{S3}$, QVDF).
Every edge is differentiable, so the whole picture is one computational
graph in the FTT sense:

```
 given OD d ──Δ──▶ link loads q ──A^T·τ──▶ Q̂ (projected)     [forward only]
                                            │  residual r (§4, informational)
 measured 𝒬,𝒳 ──unfold/decompose──▶ 𝒢, U, V, W  (AI zone, §3)
        │                              │
        └──deficit u──▶ episodes ──▶ (D/C) ──QVDF──▶ P̂, v̂_t2  [stage 2–5]
```

Gradient-based training *could* flow end-to-end through this graph (that is
the PINN/CG line); cbi_plus instead solves the physics edges in closed form
(stage 5's exact round-trip) and uses the graph as the **organizing
contract**: any engine that consumes or produces one of these tensors plugs
in without touching the others.

## 3. The AI zone — decomposition of the state tensor

**Mode unfoldings.** $X_{(1)} \in \mathbb{R}^{S \times TD}$ (space),
$X_{(2)} \in \mathbb{R}^{T \times SD}$ (time-of-day),
$X_{(3)} \in \mathbb{R}^{D \times ST}$ (days).

**HOSVD / Tucker.** With $U, V, W$ the leading left singular vectors of the
three unfoldings and core $\mathcal{G} = \mathcal{X} \times_1 U^{\!\top}
\times_2 V^{\!\top} \times_3 W^{\!\top}$:

$$\mathcal{X} \;\approx\; \mathcal{G} \times_1 U \times_2 V \times_3 W,
\qquad (r_1, r_2, r_3) = \text{mode ranks}.$$

Interpretation is physical, not generic: columns of $U$ are **spatial
bottleneck modes** (plotted against milepost they localize the recurring
bottlenecks), columns of $V$ are **daily rhythm modes** (AM/PM commute
shapes), columns of $W$ are **day-type modes** (weekday/weekend/event). The
*effective mode ranks* (participation ratio of each unfolding's spectrum)
are the corridor's observability: a rank-(3,4,2) corridor is reconstructible
from ~3 spatial × 4 temporal × 2 day patterns — which is why completion from
sparse probes works at all.

**The three working decompositions** (all implemented, numpy-only):

| Decomposition | Model | Use in this platform |
|---|---|---|
| Soft-Impute (matrix) | $\min \|X\|_*$ s.t. $X_\Omega = M_\Omega$ | masked-cell reconstruction (ai_arena) |
| SiLRTC (3-D tensor) | $\min \sum_n w_n\|X_{(n)}\|_*$ | cross-mode completion; beats per-lane 2-D by ~30 % at low probe penetration |
| RPCA | $X = L + S$, $\min\|L\|_* + \lambda\|S\|_1$ | recurrent ($L$) vs anomaly ($S$) — the label-free abnormal-cell view |

## 4. Usefulness metrics — the falsifiable claims

The write-up's purpose is a testable statement: *tensor structure carries
usable information*. Four measurements, all reproducible in-repo:

1. **Compressibility.** Variance explained vs mode rank (price-of-rank per
   mode). Useful iff effective ranks ≪ (S, T, D).
2. **Reconstruction.** Held-out masked-block MAE of the decomposition
   engines vs naive baselines (ai_arena; see the engine-comparison page —
   and note the honest caveat that masking geometry and training span decide
   the winner).
3. **Anomaly energy.** $\|S_{\cdot d}\|_1$ per day from RPCA, compared with
   the official abnormal-cell labels (CBI Lab, Act 2½ — the two definitions
   *disagree informatively*).
4. **Flow-through residual (OD-free).** Along the sorted chain, conservation
   gives $r_{e,t} = q_{e+1,t} - q_{e,t} - (\text{ramp exchange})_{e,t}$.
   With the FTT projection $\hat{\mathcal{Q}}$ from *given* OD, the residual
   $\| \mathcal{Q} - \hat{\mathcal{Q}} \|$ is reported **as information
   only** (exactly v4's weight-0 OD-consistency) — a diagnostic of demand-
   data quality, never an estimator.

## 5. Non-goals (stated so nobody drifts)

- **No dynamic OD estimation** and no path-flow recovery: $\Delta, d$ stay
  fixed inputs. Inverting them is a different problem with different
  identifiability pathologies.
- No claim that decomposition replaces physics: the arena shows completion
  families lose to physics-anchored persistence on short spans; the QVDF
  round-trip is exact where the tensor view is approximate. **The tensor is
  the data structure; the physics is the model.** The value is in the
  bridge, not a takeover in either direction.

*Engine: `cbi_pipeline/flow_tensor.py` implements §3–§4 and emits the
mode-spectrum figures and residual tables; see benchmarks/flow_tensor_demo.*
