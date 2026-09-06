# Perft correctness suite

Perft counts the number of legal leaf positions reachable after an exact number of plies. It is a correctness test for move generation and state transitions, **not** an Elo or search-speed benchmark.

The M1 implementation deliberately uses `Position::reference_after`, so these counts validate attack geometry, special-move semantics, king safety, and the immutable reference transition together. M2 will add a fast make/unmake perft path and require identical counts.

## Canonical gates

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

This position exercises castling, checks, pins, sliding pieces, and a broad tactical move tree.

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

This compact endgame is useful for en-passant and king-safety edge cases.

## Policy

- Pull requests touching move generation or state transitions must keep the CI perft subset green.
- Deeper counts belong in release/nightly validation as the fast transition becomes available.
- A wrong count is a correctness failure; performance work stops until it is explained.
- Perft NPS is tracked separately from engine playing strength.

Reference values are the standard Chess Programming Wiki perft suite:
https://www.chessprogramming.org/Perft_Results
