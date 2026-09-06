# M4 tapered geometric PSQT evaluator v1

Status: **candidate / not yet accepted**

## Hypothesis

The accepted engine has a much stronger search than its material-only static evaluator. A very cheap tapered piece-square model should add useful positional knowledge without sacrificing enough throughput to offset the gain.

## Isolated delta

Search, qsearch, PVS, TT, time management and move ordering are unchanged. Only `chess-eval::evaluate` changes.

The evaluator adds:

- material-derived game phase (`N=1, B=1, R=2, Q=4`, full phase 24);
- separate middle-game/end-game piece-square tables;
- compile-time table generation from transparent geometric rules rather than copied engine tables;
- vertical mirroring so both colours share the same tables;
- one tapered interpolation at the end.

V1 placement knowledge is deliberately small:

- pawn advancement plus tiny central-file preference;
- strong knight centralisation;
- milder bishop centralisation;
- rook advancement/seventh-rank activity;
- weak queen centralisation;
- middle-game king home/castled preference;
- end-game king centralisation.

Mobility, pawn structure, passed-pawn classification, bishop pair, rook open files, king attack maps and learned terms are explicitly excluded so their marginal value can be tested later.

## Runtime design

- no allocation;
- no legal move generation;
- no attack-map generation;
- iterate the 12 existing piece bitboards;
- one material/count calculation per bitboard;
- one table lookup per piece;
- tables are compile-time constants;
- no evaluator state is added to `Position`.

The first version recomputes these cheap terms from bitboards. Incrementalisation is a separate optimization and must earn its complexity through measured NPS/latency gains.

## Correctness checks

Tests cover:

- exact start-position symmetry;
- side-to-move score sign;
- central vs corner knight preference;
- advanced-pawn endgame preference;
- centralised endgame king preference.

## Evidence plan

1. formatting, strict Clippy, debug/release tests;
2. inspect deterministic search signature/score drift rather than treating it as a golden failure automatically;
3. run 100 paired games at `1+0.01` against accepted PVS/material baseline `339dcec0bf949c968f8ce5401c1f776108d2a691` on the frozen 100-position opening suite;
4. accept only on positive equal-time strength evidence.

If v1 wins, its accepted evaluator becomes the predecessor for isolated mobility/pawn/rook/king ablations. The geometric table values remain tuneable parameters, not doctrine.
