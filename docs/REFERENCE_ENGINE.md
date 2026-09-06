# Reference Engine

Status: **M3 baseline in progress — measured alpha-beta, interruptible limits and game clocks**

The reference engine is intentionally conventional and transparent. Its purpose is to give every later evaluator, pruning rule, graph scheduler and learned component a stable opponent and debugging oracle.

## Crate boundary

```text
chess-core
    ↑
chess-eval
    ↑
chess-search
    ↑
chess-engine
    ↑
chess-uci
```

`chess-core` owns legal chess and reversible state. `chess-eval` assigns an opinion to an already-valid position. `chess-search` chooses among legal moves. `chess-engine` owns persistent search/game orchestration and time policy. `chess-uci` translates the standard protocol into those public operations.

The dependency direction is strict: neither legal chess nor position identity may depend on evaluation, search, clocks or protocol state.

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

The first search is negamax with alpha-beta pruning.

Properties that are requirements rather than temporary implementation details:

- recursive traversal uses one mutable position and make/unmake;
- the public immutable API may clone once at its boundary, never once per child;
- checkmate and stalemate are recognized independently of static evaluation;
- mate scores encode distance from the root;
- a search must restore the supplied mutable position exactly;
- node counts are deterministic for a fixed implementation and position.

## M3.2 iterative deepening and transposition memory

A reusable `Searcher` owns bounded search state. Iterative deepening runs depths `1..=N` and deliberately retains the same transposition table between iterations.

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

## M3.3 cooperative limits and worker ownership

Search cancellation is expressed through the small `SearchControl` interface. The normal deterministic reference path uses `NeverStop`; dynamically limited searches use an engine-owned control object that can observe:

- node count;
- a hard deadline;
- a cloneable external `StopToken`.

An interrupted recursive search unwinds every speculative move. Iterative deepening only publishes a fully completed iteration, with a legal depth-zero fallback if interruption happens before depth one finishes.

The UCI executable runs mutable `Engine` / `Searcher` / TT state on one long-lived worker thread. The input thread keeps only a command sender and `StopToken`, so asynchronous `stop` does not require a mutex around search state.

## M3.4 protocol-neutral clock policy

`chess-engine::ClockState` converts game-clock data into the current hard move budget. UCI merely selects the current side's clock before calling that policy.

The first pinned allocation rule is deliberately transparent:

1. reserve 5% of remaining time;
2. divide spendable time by `movestogo`, or 30 by default;
3. add 75% of one increment;
4. never exceed the spendable clock after reserve.

The policy is intentionally not treated as optimal. Once match infrastructure exists, alternative allocation rules must earn their place under equal game conditions.

## Score convention

- ordinary evaluation uses centipawn-like integers;
- positive means good for the side to move;
- `0` is equal/stalemate under the current baseline;
- forced mate occupies a reserved range near `±30000`;
- faster wins and slower losses are preferred by incorporating ply into mate scores.

## Deterministic reference signature

The versioned `reference-search-v1` suite runs in CI and currently pins:

```text
0xad74d2111aea484e
```

The signature incorporates deterministic scores, best-move encodings, nodes and TT hits across a small position suite. Ordinary search refactors that unintentionally change search behaviour therefore fail visibly. An intentional search/evaluation improvement may change the signature, but the new baseline must be inspected and accepted explicitly.

## Evidence gates

The reference engine currently requires all of the following:

1. start-position search returns a legal move;
2. mutable search leaves its root bit-exactly unchanged;
3. a forced mate-in-one is found at depth one;
4. stalemate returns no move and a zero score;
5. iterative deepening reaches the same final score as exact search;
6. iterative deepening demonstrates transposition reuse;
7. disabling the table entirely preserves correctness;
8. mate-score transposition normalization is tested explicitly;
9. node/deadline/external-stop interruption preserves the root and returns a legal completed/fallback result;
10. the game-clock allocation rule is pinned by exact unit tests and never spends the reserved tail;
11. UCI game clocks select the clock of the actual side to move;
12. formatting, strict Clippy, debug tests, release tests and the deterministic reference signature are green.

The remaining M3 qualification work is draw/history correctness plus reproducible match infrastructure and a first measured baseline. Quiescence and stronger chess knowledge begin only after that control group is trustworthy.

## Why this remains after the advanced engine exists

The classical engine is not scaffolding to delete. It is the control group for the research programme. If a sparse DAG, neural policy, uncertainty scheduler or other experimental component cannot beat this baseline under equal resources, that component has not justified its complexity.
