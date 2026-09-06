# M4 tapered geometric PSQT evaluator v1

Status: **accepted candidate / qualified for production**

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

Formatting, strict Clippy, focused evaluator/search/core tests and the full repository CI gate passed after the reviewed deterministic baseline was updated.

## Deterministic search review

The evaluator necessarily changes scores, ordering consequences and therefore the deterministic search signature. The resulting `reference-search-v6` baseline was reviewed case-by-case rather than accepted as an opaque hash change.

Reviewed signature:

```text
reference-search-v6
0xed4d9e0addb78419
```

Notable behavior includes startpos preferring `Nb1-c3` rather than a material-equivalent generator-order move. The promotion fixture chooses `Ka1-b2` at the shallow reviewed depth while the promotion remains available to qsearch; this was inspected rather than treated as a malformed promotion regression.

## Equal-time qualification

Candidate source/match revision: `477affae90c6d42733dace7414112b8a0c5a4799`.

Accepted predecessor: PVS/material baseline `339dcec0bf949c968f8ce5401c1f776108d2a691`.

Protocol:

- 100 games / 50 colour-reversed opening pairs;
- `1+0.01`;
- frozen `m3-uho-lichess-100-v1.epd` suite;
- pinned Fastchess alpha 1.8.2;
- no search, qsearch, TT, move-ordering or time-management changes in the candidate.

Result:

```text
Wins:      62
Draws:     26
Losses:    12
Score:     75.00%
Elo:       +190.85 +/- 64.16
LOS:       100.00%
Pentanomial: [0, 4, 12, 14, 20]
```

Retained run/evidence:

- GitHub Actions run: `34048929087`;
- artifact: `m4-eval-psqt-vs-material-477affae90c6d42733dace7414112b8a0c5a4799` (artifact id `9994002994`);
- candidate executable SHA-256: `0fe324c9d059e5df6d4649e262dc4317b47452f233526036d8ae47385ce274fb`;
- predecessor executable SHA-256: `9f413d1c141cb252568418913dda04e53f9f7abb9dcb176f031022096eac7da9`;
- Fastchess SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`;
- opening-suite SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`.

## Decision

Accept E1. The gain is large, statistically decisive under the frozen equal-time protocol, and comes from an intentionally cheap isolated evaluator change.

E1 becomes the predecessor for isolated mobility, pawn-structure, rook-activity and king-safety experiments. Search heuristics such as LMR/history should be retested only as independent candidates on top of the stronger evaluator rather than assumed to compose positively.
