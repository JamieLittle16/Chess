# M5 joint classical evaluator v2 — qualification dossier

Status: **experimental / not production-qualified**.

## Why this is a materially new hypothesis

Production evaluation is still the accepted E1+E4 control: material, a tapered geometric PSQT,
bishop pair, and rook open/semi-open files. Multiple isolated handcrafted terms were rejected during
M4, and the first tiny NNUE/residual NNUE was rejected decisively inside search despite improving
static Stockfish CP RMSE.

This experiment therefore does **not** retry those terms independently. It treats the accepted
classical evaluator as a fixed prior and adds one jointly fitted, low-dimensional tapered residual.
The feature set is intentionally small enough for the existing 2,500-position leakage-safe teacher
corpus to constrain it, and cheap enough to preserve the search/evaluation tradeoff that the first
full-refresh NNUE violated.

## Frozen feature set

For each side, the residual extracts 21 integer features without heap allocation or legal move
generation:

- doubled pawns;
- pawn islands;
- isolated pawns;
- supported pawns;
- passed pawns split by relative ranks 2..6;
- pawn-safe knight/bishop/rook/queen mobility;
- rook on the seventh rank;
- pawn-supported minor outposts not attacked by enemy pawns;
- king pawn shield;
- open files adjacent to the king;
- enemy attack coverage of the king ring;
- pawn attacks on enemy non-pawns, material weighted;
- central pawn control;
- central occupancy.

The side difference is tapered with the same 24-unit phase clock as the accepted evaluator.

## Frozen fits

Both variants use the frozen 2,500-position Stockfish-19 teacher corpus from NNUE-4, grouped by
canonical opening root: 2,029 train / 228 validation / 243 holdout. No holdout position was used to
fit weights.

`cp` is a strongly ridge-regularized fit to the clipped Stockfish centipawn residual over the
accepted classical evaluator.

`wdl` uses the same features and regularization but fits a 100-cp-scaled logit transform of the
Stockfish WDL expectation. This is included because static CP RMSE alone failed badly as a search
selection criterion in the first residual-NNUE experiment.

The quantized integer tables are frozen in `crates/chess-eval/src/classical_v2.rs`. They are enabled
only when `CHESS_EXPERIMENTAL_CLASSICAL_V2=cp` or `wdl` is present at process startup. With the
environment variable absent, `evaluate()` returns the exact accepted `evaluate_classical()` score.

## Qualification order

1. strict workspace CI and focused evaluator tests;
2. verify the reference path preserves the accepted deterministic search signature;
3. measure candidate NPS/node throughput relative to the same-binary classical reference;
4. independent 100-game paired `1+0.01` screens for `cp` and `wdl`, with distinct frozen seeds;
5. reject immediately if both are materially negative;
6. if one variant has a substantial positive signal, run a fresh-seed 200-game acceptance against
   the strongest current `main` before any production merge;
7. only after a successful acceptance should the experimental switch and unused fit be removed and
   the winning source be materialized as production architecture.

The intended bar is not another tiny marginal feature. This work is being evaluated as a
high-ceiling evaluator replacement programme. Equal-time Elo remains decisive.
