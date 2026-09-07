# M5 joint tapered PSQT v1

## Hypothesis

The accepted E1+E4 evaluator is cheap but contains a very low-dimensional hand-written geometric PSQT. The jointly fitted classical-v2 CP residual demonstrated a real search-facing signal (+70.44 +/-57.32 Elo at equal nodes), but its attack/mobility extractor reduced search throughput enough that the first equal-time screen was only modestly positive.

This experiment asks whether most of that additional positional information can be moved into a substantially cheaper representation: tapered piece-square correction tables plus only inexpensive structural features. The candidate deliberately excludes slider mobility, king-ring attack unions, legal move generation and any heap allocation.

## Frozen model

The accepted classical evaluator is retained as the prior. V1 adds:

- 6 piece types x 32 color-relative/file-mirrored squares x MG/EG = 384 tapered PSQT correction coefficients;
- 19 cheap structural features x MG/EG = 38 coefficients;
- one side-to-move tempo correction;
- total fitted coefficients: 423.

Cheap structural features are doubled pawns, pawn islands, isolated pawns, supported pawns, passed-pawn ranks 2-6, rook seventh rank, minor outposts, king shield, king open files, pawn threats, central pawn control, central occupancy, bishop pair, rook open file and rook semi-open file.

The frozen ridge fit used alpha=100 over the existing leakage-safe Stockfish-19 teacher corpus used by the M5 strength lab:

- 2,500 records total;
- 2,029 train;
- 228 validation;
- 243 holdout;
- corpus SHA-256: `0fe794272d2a8198f82dd81894b3248ad2dfcc8be75595c155db4753556ea2da`.

Approximate clipped-CP RMSE before search qualification:

| evaluator | train | validation | holdout |
| --- | ---: | ---: | ---: |
| accepted E1+E4 control | 411.19 | 434.65 | 488.27 |
| frozen joint tapered PSQT v1 | 338.36 | 383.82 | 409.63 |

Static teacher fit is only a pre-screen signal. Equal-time games decide whether the model is useful.

## Runtime design

The experiment is selected before process startup with `CHESS_EXPERIMENTAL_JOINT_TAPERED_PSQT_V1=1`.

The production path with the variable unset remains the exact accepted evaluator. The candidate performs baseline material/geometric-PSQT and fitted PSQT correction lookups in the same piece traversal, then adds only cheap structural terms. No slider attack generation is introduced by the fitted model.

## Qualification

1. strict fmt/Clippy/workspace release tests;
2. reference path must retain `reference-search-v8` signature `0x4c3bbe8701fbbb68`;
3. candidate deterministic drift is recorded, not automatically blessed;
4. 100 paired equal-time games at `1+0.01`, Hash=32 MiB, concurrency 1, frozen UHO suite and pinned Fastchess;
5. compare candidate/reference nodes and NPS as well as Elo;
6. only a substantial positive screen earns fresh-seed 200-game marginal acceptance over the strongest current `main`.

## Decision

Pending screen. A strong result would justify training the same architecture on a much larger teacher corpus before adding expensive dynamic features. A weak result means static teacher-error improvement is again not translating to search strength and the project should move to the coordinated search-generation programme rather than hand-retune these tables after seeing game outcomes.
