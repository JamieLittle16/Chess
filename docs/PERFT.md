# Perft correctness suite

Perft counts the number of legal leaf positions reachable after an exact number of plies. It is a correctness test for move generation and state transitions, **not** an Elo or search-speed benchmark.

The first M1 implementation used `Position::reference_after` recursively. M2 keeps that immutable transition as the correctness oracle but runs production perft through `generate_legal_moves_mut`, `Position::make_move`, and `Position::unmake_move`. The root is cloned at most once; recursive children reuse one working position.

This means the same canonical counts now gate both chess correctness and the reversible state machine.

## Canonical gates

The cross-cutting qualification suite uses the six standard Chess Programming Wiki positions. Ordinary tests validate depths 1-3 for all six positions. A release-only deep qualification is ignored during normal unit-test runs and executed explicitly by `scripts/check.sh` and CI.

### Initial position

```text
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1
```

| Depth | Nodes |
|---:|---:|
| 1 | 20 |
| 2 | 400 |
| 3 | 8,902 |
| 4 | 197,281 |
| 5 | 4,865,609 |
| 6 | 119,060,324 |

The deep CI gate uses depth 5.

### Position 2 / Kiwipete

```text
r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1
```

| Depth | Nodes |
|---:|---:|
| 1 | 48 |
| 2 | 2,039 |
| 3 | 97,862 |
| 4 | 4,085,603 |
| 5 | 193,690,690 |

This position exercises castling, checks, pins, sliding pieces, and a broad tactical move tree. The deep CI gate uses depth 4.

### Position 3

```text
8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1
```

| Depth | Nodes |
|---:|---:|
| 1 | 14 |
| 2 | 191 |
| 3 | 2,812 |
| 4 | 43,238 |
| 5 | 674,624 |
| 6 | 11,030,083 |

This compact endgame is useful for en-passant and king-safety edge cases. The deep CI gate uses depth 5.

### Position 4

```text
r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1
```

| Depth | Nodes |
|---:|---:|
| 1 | 6 |
| 2 | 264 |
| 3 | 9,467 |
| 4 | 422,333 |

This stresses promotions, castling-right transitions and constrained legal replies. The deep CI gate uses depth 4.

### Position 5

```text
rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8
```

| Depth | Nodes |
|---:|---:|
| 1 | 44 |
| 2 | 1,486 |
| 3 | 62,379 |
| 4 | 2,103,487 |

This is a compact tactical/promotion regression position that has historically exposed move-generation bugs. The deep CI gate uses depth 4.

### Position 6

```text
r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10
```

| Depth | Nodes |
|---:|---:|
| 1 | 46 |
| 2 | 2,079 |
| 3 | 89,890 |
| 4 | 3,894,594 |

This exercises a dense middlegame with pins, checks and slider interactions. The deep CI gate uses depth 4.

## Cross-cutting state-machine qualification

`crates/chess-core/tests/core_qualification.rs` deliberately tests subsystem interactions rather than one implementation in isolation. Across deterministic playouts from opening, middlegame, endgame, castling, en-passant and promotion roots it checks:

1. incremental Zobrist identity equals full reconstruction;
2. `Position::to_fen` reparses to the exact same state;
3. mutable and immutable legal move generation agree and restore the position;
4. tactical move generation equals the tactical subset of full legal generation;
5. every generated legal move matches the independent `reference_after` transition;
6. every make/unmake pair restores the exact prior position;
7. complete playout histories unwind exactly to their roots.

This is intentionally deterministic: failures are reproducible from the recorded root, seed and ply.

## Validation layers

1. `reference_after` remains a simple immutable semantic oracle.
2. Every reversible transition is differential-tested against that oracle.
3. `generate_legal_moves_mut` must restore its working position exactly.
4. `perft_mut` must restore the root exactly after the complete recursive traversal.
5. Incremental Zobrist state must agree with full reconstruction.
6. FEN serialization must reconstruct the full public position state.
7. The resulting node counts must match independently published perft values.

A bug therefore has multiple chances to be detected rather than one optimized implementation validating itself.

## Policy

- Pull requests touching move generation or state transitions must keep the ordinary qualification suite green.
- `./scripts/check.sh` and CI also run the deeper release perft qualification.
- A wrong count, state round-trip mismatch or oracle disagreement is a correctness failure; performance work stops until it is explained.
- New stateful core optimisations should add an invariant test at the narrowest useful layer and, when appropriate, extend this cross-cutting qualification suite.
- Perft NPS is tracked separately from engine playing strength.

Reference values are the standard Chess Programming Wiki perft suite:
https://www.chessprogramming.org/Perft_Results
