# External GPT dialogue — "Ask Me About Travel Demand Modeling"

Goal (owner request): hold a dialogue with the public custom GPT at
`chatgpt.com/g/g-6978d916e73881918d15639230fb4515-ask-me-about-travel-demand-modeling`
to learn how the travel-demand-modeling community frames congestion
bottlenecks, and harvest improvement items for CBI/QVDF.

## Status

**Attempted 2026-07-08 — browser bridge not connected.** The Claude
Chrome extension was unreachable in this session (the GPT requires a
logged-in chatgpt.com browser session; it cannot be fetched headlessly).
Retry path: open Chrome with the extension signed in and say "retry the
GPT dialog" — the script below runs as-is.

Fallback executed instead: a literature RAG covering the same ground —
distilled Q&A with sources in
[../knowledge/WEB_RAG_BOTTLENECK_NOTES.md](../knowledge/WEB_RAG_BOTTLENECK_NOTES.md).

## The prepared dialogue script (5 turns)

1. "How do practicing travel demand modelers represent freeway bottlenecks
   today, and where do BPR-style volume-delay functions break down for
   corridors with daily queue spillback?"
2. "If a diagnostic tool could hand you, per bottleneck: onset time, worst
   point, recovery time, congestion duration, discharge rate μ, and a
   D/C→duration power law calibrated from detectors — where exactly in a
   four-step or activity-based workflow would you plug those in?"
3. "What evidence would make you trust an externally calibrated
   queue-aware VDF (like a QVDF) enough to replace your BPR parameters on
   a screenline — and what validation would your reviewers demand?"
4. "How does your community treat travel-time reliability (LOTTR/TTTR)
   versus duration-of-congestion measures in project prioritization, and
   which one moves funding decisions in practice?"
5. "What is the biggest data or vocabulary mismatch you see between
   operations-side congestion diagnostics and demand-side modeling teams —
   what would a shared 'issue object' between the two need to carry?"

Each answer gets logged verbatim below the question; disagreements with
our framing become register rows (the point is to learn, not to win).

## Provisional answers (literature fallback) and adopted improvements

The fallback RAG answered Q1/Q2 substantively (see knowledge notes): BPR
breaks at v/c ≥ 1 by construction; static assignment assumes no spillback
and within-period stationarity; the field's fixes (FD-based modified VDFs,
residual-queue assignment) are converging on exactly what QVDF ships.
Adopted as register items:

| ID | improvement | status |
|---|---|---|
| KNW-1 | INTRODUCTION/AMS bridge: state plainly that QVDF is the calibrated queue-aware VDF the modified-VDF literature is reaching for | DONE v2.9.0 |
| KNW-2 | INTELLECTUAL_LINEAGE: cite modified-VDF + residual-queue-assignment literature as the demand-side convergence | DONE v2.9.0 |
| KNW-3 | benefit tokens: use the I-405 Sepulveda widening story as the concrete public example of the induced-demand caveat | DONE v2.9.0 |
| KNW-4 | live GPT dialogue Q3–Q5 (trust evidence, reliability-vs-duration in funding, shared issue-object fields) | PENDING browser |
