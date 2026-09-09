# Testing and qualification contract

Little Gambit treats correctness, performance and playing strength as different kinds of evidence. A patch is not accepted merely because it compiles, searches faster, finds a tactical example, or wins a small match.

This document defines the standing validation layers for the Rust engine.

## 1. Ordinary workspace gate

Every pull request must pass the pinned Rust 1.98.1 workspace gate:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --workspace --all-features --no-deps
cargo test --workspace --all-features
cargo test --workspace --all-features --release
cargo run --release --quiet -p chess-bench
```

The workspace forbids `unsafe` Rust. Introducing unsafe code requires an explicit architectural decision, measured benefit, documented invariants and a safe reference path where practical.

## 2. Chess-core qualification

The core is validated independently of search and evaluation.

### Canonical perft

`crates/chess-core/tests/core_qualification.rs` runs all six standard perft positions through depth three during ordinary tests. CI additionally runs the ignored release-only deep qualification, covering roughly 16 million leaf nodes.

A wrong perft count is a chess-correctness failure. Search or Elo work stops until it is explained.

### Differential state-machine testing

Deterministic multi-root playouts exercise ordinary moves, checks, pins, castling, en-passant and promotions. At every visited state the suite checks:

- mutable legal generation leaves the root unchanged;
- tactical generation matches the tactical subset of full legal generation;
- every legal `make_move` result matches the independent immutable `reference_after` oracle;
- every `unmake_move` restores the exact parent state;
- incremental Zobrist identity matches full reconstruction;
- FEN serialization reparses to the same position;
- complete playout histories unwind exactly to their roots.

The optimized reversible transition therefore does not validate itself.

### External chess-rules oracle

Core changes additionally run a path-triggered differential against pinned `python-chess==1.999` in an isolated virtual environment. `scripts/core_oracle_diff.py` drives the test-only `oracle_bridge` example and compares two independent rules implementations.

The standing qualification uses 512 deterministic positions drawn from curated edge cases and seeded legal playouts. It compares:

- the complete sorted legal-move set on all 512 positions;
- the exact resulting FEN after every legal move on the first 192 positions, including side to move, castling rights, en-passant target and move clocks;
- depth-two perft on the first 64 positions.

The first certified execution covered 5,624 cross-implementation queries: 512 move sets, 5,048 legal child transitions and 64 perft roots. The external dependency remains test-only and does not enter the Rust workspace dependency graph or production binaries.

This layer exists because an optimized implementation and an in-repository reference implementation can theoretically share the same misunderstanding of a chess rule. Agreement with a separately maintained rules engine substantially reduces that common-mode risk.

## 3. Search-state qualification

`crates/chess-search/tests/search_state_qualification.rs` tests invariants that should remain true across search redesigns rather than pinning fragile move-order details.

Standing cases include:

- interruption at many recursive node boundaries restores the root exactly;
- a `Searcher` remains reusable after an interrupted search;
- forced one-entry TT collisions cannot reuse foreign-position data;
- TT entries cannot override 50-move draw context even though the halfmove clock is excluded from TT identity;
- repetition identity correctly normalizes irrelevant en-passant metadata;
- the second occurrence is live while the third occurrence is a draw;
- checkmate takes precedence when a mating move reaches halfmove 100.

Mate-score conversion, TT bounds, qsearch-in-check behaviour, stalemate and basic draw precedence also have focused unit tests beside the implementation.

Tests should prefer semantic invariants, score relations and legal-move membership over exact node counts or exact best moves unless determinism itself is the invariant being tested.

## 4. Engine-orchestration qualification

`crates/chess-engine/tests/orchestration_qualification.rs` tests the boundary where persistent game state meets reusable search state.

It covers:

- a real legal move sequence reaching the second and third occurrences of the same repetition identity;
- search preserving the current position and complete repetition history;
- hash-table resizing preserving game state;
- stop-token interruption followed by safe reuse of the same engine;
- multiple node-budget interruption points over a nontrivial game history.

Protocol tests in `chess-uci` separately require transactional `position ... moves ...` handling, legal move parsing, preserved threefold context, legal fallbacks under immediate stop and correct clock-side selection.

## 5. Real-network derived-state certification

Learned evaluation adds derived state that ordinary classical tests cannot fully exercise.

Two path-triggered GitHub Actions gates use the exact certified Gestalt network:

```text
gestalt-b840.nnue
SHA-256 956a6afcce5de1cdbc953ae3817ff760f3e6036441f34dcd524d6e2e7d0e71f6
```

### Gestalt incremental certification

Changes to chess-core or the incremental Gestalt implementation run the real-network differential make/unmake harness. Incremental accumulator values must continue to agree with reconstructed state throughout forward and reverse play.

### Gestalt search-state certification

Changes to search, engine orchestration or evaluation run root-analysis parity plus the search-state and engine-orchestration qualification suites with `CHESS_GESTALT_NETWORK` enabled. This specifically guards against stale accumulator state after pruning, interruption, root changes or `Searcher` reuse.

The downloaded network is checksum-pinned and is not retained in repository artifacts.

## 6. Deterministic benchmark identity

`chess-bench` provides a reviewed deterministic search signature. Correctness-oriented or semantics-preserving patches must explain any unexpected signature change.

The signature is not an Elo metric and is not a substitute for paired games.

## 7. Performance evidence

A performance patch must identify the workload it improves and demonstrate a whole-search benefit where applicable.

Prefer:

- repeated fixed-position measurements;
- fixed-node comparisons when tree semantics should be unchanged;
- total search NPS/wall time rather than isolated microbenchmarks alone;
- evaluator-call, qnode or TT statistics when they explain the mechanism.

If a supposedly semantics-preserving optimization changes chess decisions or fixed-node behaviour, treat that as a correctness/search-semantics question before interpreting timing numbers.

## 8. Strength evidence

Playing-strength changes are qualified separately from correctness.

The normal hierarchy is:

1. correctness gate;
2. equal-node screen for decision quality when appropriate;
3. throughput measurement;
4. equal-time paired games;
5. SPRT for production promotion;
6. external Stockfish calibration only for meaningful generation checkpoints.

Self-play Elo is evidence for patch selection, not an arithmetic update to an absolute external rating.

## 9. Regression-test rule

Every bug fix should add the narrowest deterministic regression that would have failed before the fix. Every correctness-sensitive optimization should add or reuse an independent invariant capable of detecting drift.

When a test fails, classify the failure before changing code:

1. real engine bug;
2. invalid test assumption;
3. intentional semantic change requiring new qualification;
4. nondeterministic/environmental failure.

Do not weaken a test merely to make CI green.

## 10. Cost discipline

Keep the default developer loop fast. Expensive but deterministic checks belong in explicit release/path-triggered CI gates rather than every inner-loop test run.

That lets V16 search experimentation remain rapid while preserving a substantially stronger correctness boundary around the engine.
