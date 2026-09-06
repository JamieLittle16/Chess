# Reference Engine

Status: **M3 baseline in progress — draw-correct, interruptible and timed**

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

`chess-core` owns legal chess and reversible state. `chess-eval` assigns an opinion to an already-valid position. `chess-search` chooses among legal moves. `chess-engine` owns persistent game/search orchestration, game history and time policy. `chess-uci` translates the standard protocol into those public operations.

The dependency direction is strict: neither legal chess nor canonical position state may depend on evaluation, search, clocks or protocol state.

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

## M3.3 draw and history semantics

Draw context is deliberately not embedded into the transposition-table identity.

`chess-core` exposes two related identities:

- `zobrist_key()` is the conservative TT identity and includes the exact en-passant target;
- `repetition_key()` follows repetition semantics and removes an en-passant component when no legal en-passant capture exists, including king-pinned cases.

`chess-engine` owns the repetition-key sequence for actual game positions. It appends one key only when a real game move is applied. Search receives all known keys before its root and keeps speculative search-path keys in a fixed 256-entry array owned by `Searcher`; recursive draw checking therefore performs no heap growth.

Search currently recognizes:

- threefold repetition from game history plus the local search path;
- the 50-move rule from the halfmove clock;
- exact dead-material classes: bare kings, a single bishop/knight against a bare king, and bishop-only positions where every bishop is confined to the same square colour.

Checkmate takes precedence over a claimable draw. Draw adjudication also happens **before TT probing**, and history-dependent draws are never stored as context-free exact TT results. This prevents a draw score reached under one history from contaminating the same board reached under another.

UCI `position ... moves ...` parsing preserves every preceding repetition key transactionally. If any supplied move is malformed or illegal, neither the board nor its history is committed.

## M3.4 cooperative limits and worker ownership

Search cancellation is expressed through the small `SearchControl` interface. The normal deterministic reference path uses `NeverStop`; dynamically limited searches use an engine-owned control object that can observe:

- node count;
- a hard deadline;
- a cloneable external `StopToken`.

An interrupted recursive search unwinds every speculative move. Iterative deepening only publishes a fully completed iteration, with a legal depth-zero fallback if interruption happens before depth one finishes.

The stop check occurs before even an exact root TT hit, so a cached result cannot make an interruptible search ignore an already-issued stop request.

The UCI executable runs mutable `Engine` / `Searcher` / TT state on one long-lived worker thread. The input thread keeps only a command sender and `StopToken`, so asynchronous `stop` does not require a mutex around search state.

## M3.5 protocol-neutral clock policy

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
- `0` is equal or a recognized draw under the current baseline;
- forced mate occupies a reserved range near `±30000`;
- faster wins and slower losses are preferred by incorporating ply into mate scores.

## Deterministic reference signature

The draw-aware `reference-search-v2` suite runs in CI and pins:

```text
0x1a149495c23a7d8e
```

V2 changed only one V1 case: the promotion benchmark now terminates two dead-material continuations earlier (`24 → 22` nodes and `8 → 6` TT hits), while its score and best move are unchanged. Startpos, Kiwipete, mate-net and en-passant remained bit-for-bit identical.

The signature incorporates deterministic scores, best-move encodings, nodes and TT hits across the suite. Ordinary search refactors that unintentionally change behavior therefore fail visibly. Benchmark assertion failures print the complete case report so intentional drift can be reviewed rather than accepted from a hash alone.

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
10. a cached root TT result cannot bypass external stop control;
11. threefold repetition overrides a previously cached non-draw TT result;
12. 50-move and dead-material draws are recognized, while checkmate keeps precedence;
13. legal, irrelevant and pinned en-passant repetition identities are tested separately;
14. game history is unchanged by search and UCI move sequences preserve it transactionally;
15. the game-clock allocation rule is pinned by exact unit tests and never spends the reserved tail;
16. UCI game clocks select the clock of the actual side to move;
17. formatting, strict Clippy, debug tests, release tests and `reference-search-v2` are green.

The remaining M3 qualification work is reproducible match infrastructure and a first measured baseline. Quiescence and stronger chess knowledge begin only after that control group is measurable.

## Why this remains after the advanced engine exists

The classical engine is not scaffolding to delete. It is the control group for the research programme. If a sparse DAG, neural policy, uncertainty scheduler or other experimental component cannot beat this baseline under equal resources, that component has not justified its complexity.
