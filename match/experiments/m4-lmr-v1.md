# M4 late-move reductions v1

Status: **rejected / not merged**

## Hypothesis

Accepted PVS already makes late moves cheaper when they fail low. We tested whether sufficiently late quiet moves could receive a conservative one-ply reduction while requiring full-depth verification before any reduced alpha improvement affected the node.

## Conservative v1 policy tested

At a non-check node:

- first move was always full depth;
- captures/promotions were never reduced;
- checking moves were never reduced;
- only move index 4 and later was eligible;
- only nominal depth 3 and deeper was eligible;
- eligible moves received a one-ply reduction on their initial null-window probe;
- a reduced alpha improvement was verified by a full-depth null-window probe;
- only a full-depth alpha improvement could trigger ordinary PVS full-window re-search;
- qsearch, TT, draw/cancellation semantics and evaluation were unchanged.

## Correctness and deterministic evidence

Formatting, strict Clippy, debug/release tests and the full ordinary CI gate passed. `reference-search-v5` remained bit-for-bit unchanged, which is consistent with the deliberately deeper activation thresholds.

## Equal-time screen

Candidate `b50ce70263be69ae22c7df574515c7a2c66cd3a1` versus accepted PVS `339dcec0bf949c968f8ce5401c1f776108d2a691`, 100 games at `1+0.01`, concurrency 1, frozen 100-position opening corpus with colour-reversed pairs:

- **20 wins / 64 draws / 16 losses**;
- **52.0 / 100 (52.00%)**;
- Fastchess Elo **+13.90 +/- 44.27**;
- LOS **73.22%**;
- pentanomial `[3, 7, 26, 11, 3]`.

Retained evidence:

- Actions run `34048581637`;
- artifact `m4-lmr-vs-pvs-b50ce70263be69ae22c7df574515c7a2c66cd3a1`;
- artifact ID `9993902055`;
- artifact ZIP SHA-256 `f377b432dfec766227746cade98ba2aec386f285daf7b65b6ef9516fd004c7ff`;
- candidate binary SHA-256 `a95c5f1d514525b2e2b477cf90db9b7c7d02fde5c95094e95f17ccabf2c5bb01`;
- reference binary SHA-256 `9f413d1c141cb252568418913dda04e53f9f7abb9dcb176f031022096eac7da9`.

## Decision

Reject LMR v1. The result trends positive but is statistically inconclusive and does not meet the production evidence bar established by the accepted qsearch, staged MovePicker and PVS changes. We will not promote a selective-search mechanism merely because it is conventional.

The experiment also suggests that further selective-search tuning may benefit from a stronger static evaluator. LMR can be revisited after positional evaluation is accepted, potentially with depth/move-index tables and history/policy signals. Any such version is a new experiment and must be requalified.
