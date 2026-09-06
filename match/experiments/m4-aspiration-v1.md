# M4 aspiration windows v1

Status: **candidate / not yet accepted**

## Hypothesis

Accepted PVS already benefits from good first-move ordering. Iterative deepening also gives a strong prior for the next iteration's score. Searching the next depth around that prior should reduce work when the score is stable, while progressive widening preserves correctness when the score moves materially.

## Design

- depth 1 searches the full `[-INFINITY, +INFINITY]` root window;
- later depths use a ±50 cp window around the last fully completed iteration when that score is outside the mate band;
- fail-low or fail-high doubles the symmetric window and retries the same depth;
- retries reuse the transposition table and count toward node/time limits;
- mate-range previous scores bypass aspiration and search full-window;
- a retry interrupted by node/time/stop control returns the previous fully completed iteration, never a partial result;
- root TT entries now use `Upper`, `Lower`, or `Exact` according to the active root window;
- root PVS respects the active alpha/beta window and may cut off on fail-high;
- no move is pruned or depth-reduced by aspiration itself.

No history, killers, counter-moves, null-move pruning, LMR, futility/LMP or evaluation change is bundled.

## Evidence plan

1. formatting, strict Clippy, debug/release tests and search correctness;
2. inspect deterministic `reference-search-v5` drift case-by-case rather than blindly changing the golden signature;
3. if search behavior is correct, run 100 paired games at `1+0.01` against accepted PVS `339dcec0bf949c968f8ce5401c1f776108d2a691` on the frozen 100-position opening corpus with colour reversal;
4. accept only with positive equal-time strength evidence.

## Notes

The ±50 cp starting width is deliberately a transparent first baseline, not a tuned constant. If v1 is promising but noisy, later experiments can test asymmetric/progressive widening and volatility-dependent initial windows independently.
