# M4 aspiration windows v1

Status: **rejected / not merged**

## Hypothesis

Accepted PVS already benefits from good first-move ordering. Iterative deepening also gives a strong prior for the next iteration's score. Searching the next depth around that prior should reduce work when the score is stable, while progressive widening preserves correctness when the score moves materially.

## Design tested

- depth 1 searches the full `[-INFINITY, +INFINITY]` root window;
- later depths use a ±50 cp window around the last fully completed iteration when that score is outside the mate band;
- fail-low or fail-high doubles the symmetric window and retries the same depth;
- retries reuse the transposition table and count toward node/time limits;
- mate-range previous scores bypass aspiration and search full-window;
- a retry interrupted by node/time/stop control returns the previous fully completed iteration, never a partial result;
- root TT entries use `Upper`, `Lower`, or `Exact` according to the active root window;
- root PVS respects the active alpha/beta window and may cut off on fail-high;
- no move is pruned or depth-reduced by aspiration itself.

No history, killers, counter-moves, null-move pruning, LMR, futility/LMP or evaluation change was bundled.

## Correctness and deterministic shape

Formatting, strict Clippy and focused search tests passed. All five reviewed benchmark scores and best moves stayed unchanged versus `reference-search-v5`.

The shallow work profile was also unchanged in four cases, but Kiwipete rose from 1,023 to 1,162 nodes (+13.6%) because retries added real work. The resulting unaccepted candidate signature was `14954855240633000223`; it was deliberately **not** promoted to a new reference signature because the equal-time strength screen did not justify the change.

## Equal-time screen

Candidate `4906615687f50c22a776c6cc9aa8442118fdc678` versus accepted PVS `339dcec0bf949c968f8ce5401c1f776108d2a691`, 100 games at `1+0.01`, concurrency 1, frozen 100-position opening corpus with colour-reversed pairs:

- **21 wins / 59 draws / 20 losses**;
- **50.5 / 100 (50.50%)**;
- Fastchess Elo **+3.47 +/- 38.06**;
- LOS **57.13%**;
- pentanomial `[1, 11, 25, 12, 1]`.

Retained evidence:

- Actions run `34048152508`;
- artifact `m4-aspiration-vs-pvs-4906615687f50c22a776c6cc9aa8442118fdc678`;
- artifact ID `9993782805`;
- artifact ZIP SHA-256 `68ef2fa8387aba4fd6e8358026699fec181d186291349caf3631e276d271c047`;
- candidate binary SHA-256 `94d6eb71bcb7a9d112018e0387fbf68ba65a94b914ac9611e8c064d790021f4d`;
- reference binary SHA-256 `9f413d1c141cb252568418913dda04e53f9f7abb9dcb176f031022096eac7da9`.

## Decision

Reject aspiration v1. The candidate is statistically indistinguishable from accepted PVS and makes the known Kiwipete search-shape case more expensive. The ±50 cp symmetric-window policy therefore does not earn its additional retry machinery under the current material-only evaluator and short-control protocol.

This does **not** establish that aspiration is intrinsically unhelpful. A later engine with a stronger, more stable evaluator may justify a wider, asymmetric or volatility-adaptive aspiration policy. Any such version must be a new isolated experiment.
