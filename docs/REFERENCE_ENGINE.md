# Reference Engine

Status: **M3 baseline in progress**

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

The first version intentionally has no transposition table, quiescence, history heuristics, killer moves, reductions or learned ordering. Those are layered on only after this baseline is green.

## Score convention

- ordinary evaluation uses centipawn-like integers;
- positive means good for the side to move;
- `0` is equal/stalemate under the current baseline;
- forced mate occupies a reserved range near `±30000`;
- faster wins and slower losses are preferred by incorporating ply into mate scores.

## Evidence gates

Before the reference search is considered established:

1. start-position search returns a legal move;
2. mutable search leaves its root bit-exactly unchanged;
3. a forced mate-in-one is found at depth one;
4. stalemate returns no move and a zero score;
5. formatting, strict Clippy, debug tests and release tests are green.

Next layers are iterative deepening, deterministic move ordering, a bounded transposition table, UCI orchestration and a reproducible search benchmark.

## Why this remains after the advanced engine exists

The classical engine is not scaffolding to delete. It is the control group for the research programme. If a sparse DAG, neural policy, uncertainty scheduler or other experimental component cannot beat this baseline under equal resources, that component has not justified its complexity.
