# Reference Engine

Status: **M3 baseline in progress — alpha-beta + iterative deepening + bounded TT**

The reference engine is intentionally conventional and transparent. Its purpose is to give every later evaluator, pruning rule, graph scheduler and learned component a stable opponent and debugging oracle.

## Crate boundary

```text
chess-core
    ↑
chess-eval
    ↑
chess-search
```

`chess-core` owns legal chess and reversible state. `chess-eval` assigns an opinion to an already-valid position. `chess-search` chooses among legal moves using only the public core/eval interfaces.

The dependency direction is strict: neither legal chess nor position identity may depend on evaluation or search.

## M3.1 evaluator

The first evaluator is material-only:

| Piece | Value |
| --- | ---: |
| Pawn | 100 |
| Knight | 320 |
| Bishop | 330 |
| Rook | 500 |
| Queen | 900 |
| King | 0 |

Scores are always returned from the side-to-move perspective. This makes the contract directly compatible with negamax and avoids colour-specific branches in search.

This evaluator is deliberately weak. That is useful: it is tiny enough to inspect completely and gives us a clean measurement point for every positional or learned evaluator added later.

## M3.1 search

The first search is fixed-depth negamax with alpha-beta pruning.

Properties that are requirements rather than temporary implementation details:

- recursive traversal uses one mutable position and make/unmake;
- the public immutable API may clone once at its boundary, never once per child;
- checkmate and stalemate are recognized independently of static evaluation;
- mate scores encode distance from the root;
- a search must restore the supplied mutable position exactly;
- node counts are deterministic for a fixed implementation and position.

## M3.2 iterative deepening and transposition memory

A reusable `Searcher` now owns bounded search state. Iterative deepening runs depths `1..=N` and deliberately retains the same transposition table between iterations.

The first table is intentionally simple:

- fixed entry count supplied when the `Searcher` is created;
- direct mapped by deterministic Zobrist key;
- full key retained in every entry, so index collisions are never treated as hits;
- depth-preferred replacement;
- exact/lower/upper bound classification;
- best move retained for ordering;
- mate scores normalized on store/probe so a transposition reached at a different ply retains the correct mate distance;
- zero entries is a supported configuration and produces correct search with no table.

The default table contains 32,768 entries. This is a baseline, not a permanently chosen size or replacement policy.

### Move ordering

Ordering remains deterministic and allocation-free:

1. transposition-table move when present and legal;
2. captures and promotions;
3. remaining quiet moves in generator order.

This gives alpha-beta useful structure without yet introducing history tables, killer moves or evaluator-specific policy.

## Score convention

- ordinary evaluation uses centipawn-like integers;
- positive means good for the side to move;
- `0` is equal/stalemate under the current baseline;
- forced mate occupies a reserved range near `±30000`;
- faster wins and slower losses are preferred by incorporating ply into mate scores.

## Evidence gates

The reference search currently requires all of the following:

1. start-position search returns a legal move;
2. mutable search leaves its root bit-exactly unchanged;
3. a forced mate-in-one is found at depth one;
4. stalemate returns no move and a zero score;
5. iterative deepening reaches the same final score as an exact search;
6. iterative deepening demonstrates transposition reuse;
7. disabling the table entirely preserves correctness;
8. mate-score transposition normalization is tested explicitly;
9. formatting, strict Clippy, debug tests and release tests are green.

Next layers are UCI-ready orchestration, explicit search limits/time management, a deterministic engine benchmark, then quiescence and stronger move ordering.

## Why this remains after the advanced engine exists

The classical engine is not scaffolding to delete. It is the control group for the research programme. If a sparse DAG, neural policy, uncertainty scheduler or other experimental component cannot beat this baseline under equal resources, that component has not justified its complexity.
