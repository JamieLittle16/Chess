# Roadmap

The roadmap is ordered by dependency and evidence, not by visual excitement.

## Current status

- **M0 complete** — core representation, toolchain and CI are green.
- **M1 complete** — legal chess and reference perft are green.
- **M2 complete** — reversible state and deterministic position identity are green.
- **M3 complete** — the classical reference engine is timed, draw-correct, externally measurable and now has a retained Stockfish calibration.
- **M4 in progress** — bounded quiescence, staged allocation-free move picking and principal variation search have each earned acceptance through isolated equal-time paired-game tests. SEE ordering v1 was correctly rejected after a negative screen.

## M0 — Core foundations — complete

- workspace/toolchain/CI;
- compact square, colour, piece and move domain types;
- bitboards;
- complete position storage shape;
- FEN parser;
- architecture, development and benchmark contracts.

Exit condition: CI clean and the representation invariants are tested. **Met.**

## M1 — Legal chess — complete

- leaper and sliding attacks;
- pseudo-legal generation;
- check/pin handling through legal filtering;
- fully legal move generation;
- castling, en-passant and promotions;
- published perft suite.

Exit condition: all selected reference perft positions agree through meaningful depths. **Met.**

## M2 — Reversible state and identity — complete

- compact make/unmake stack;
- fixed-size undo state;
- incremental occupancy and controlled derived state;
- deterministic incremental Zobrist hashing;
- long-play round-trip and reconstruction tests;
- independent immutable transition oracle retained for differential testing.

Exit condition: long legal sequences unmake bit-exactly and hashes reproduce. **Met.**

## M3 — Classical reference engine — complete

Implemented and qualified:

- transparent material baseline evaluator;
- negamax + alpha-beta;
- deterministic move ordering;
- iterative deepening;
- bounded transposition table;
- persistent engine orchestration;
- generic cooperative cancellation in search;
- depth, node and wall-clock limits owned by engine orchestration;
- interruptible UCI worker with single-owner engine/search state and asynchronous `stop`;
- UCI `go depth`, `go nodes`, `go movetime`, `wtime`, `btime`, `winc`, `binc` and `movestogo` support;
- protocol-neutral `ClockState` with a conservative, pinned M3 allocation policy;
- engine-owned game repetition history preserved transactionally through UCI move sequences;
- separate conservative TT identity and rule-correct repetition identity, including legal/pinned en-passant semantics;
- threefold repetition, 50-move and conservative dead-material draw adjudication before TT reuse;
- fixed-capacity search-path repetition history with no recursive heap growth;
- versioned deterministic benchmark/signature in CI;
- repository-owned paired-game qualification protocol;
- Fastchess provenance wrapper with exact runner/engine/opening hashes, command/environment capture and retained PGN/raw/UCI evidence;
- hermetic match-harness tests in CI and the local gate;
- frozen `m3-uho-lichess-100-v1` opening corpus derived deterministically from a pinned CC0 Stockfish UHO Lichess source;
- protocol-level opening suite ID/SHA-256 enforcement before a match result directory is created;
- independent Python provenance/rank/hash validation and Rust legality/nonterminal validation for all 100 openings;
- first retained external calibration: 100 games at `1+0.01` against Stockfish 19 with `UCI_LimitStrength=true`, `UCI_Elo=1320`, scoring 31 wins / 9 draws / 60 losses and Fastchess relative Elo `-103.73 +/- 71.87`.

The external result is a protocol-specific development calibration, not a FIDE rating. Its exact hashes, paired-game result and retained artifact are recorded in `docs/STRENGTH_BASELINES.md`.

`go infinite`, ponder, configurable UCI options and richer GUI-facing features remain useful compatibility work but are no longer M3 blockers. They can be added when selected harnesses/opponents require them.

Exit condition: a correctly timed, draw-correct UCI engine with a reproducible measured baseline. **Met.**

## M4 — Tactical engine — in progress

Accepted so far:

- bounded four-qply quiescence with a specialized tactical-only legal generator;
- allocation-free staged `MovePicker` with lazy tactical selection and no global sort;
- principal variation search / null-window probing for later moves.

Measured short-control gains on the frozen development protocol:

- qsearch v1 vs M3: `+281.68 +/- 58.17` Elo;
- staged MovePicker vs qsearch: `+74.06 +/- 37.99` Elo;
- PVS v1 vs staged MovePicker: `+41.89 +/- 30.29` Elo.

These are incremental equal-time development screens, not additive absolute ratings.

Rejected experiments are retained as evidence too: SEE ordering v1 was correct but scored `-13.90 +/- 33.29` Elo versus the accepted picker and was not merged.

Next high-value work:

- killer moves and quiet history ordering;
- counter-move heuristic;
- aspiration windows;
- bounded tactical TT refinements where measurements justify them;
- null-move pruning with conservative zugzwang/material gates;
- late-move reductions;
- futility and late-move pruning only after stronger ordering/reduction baselines exist;
- qsearch refinements such as selectively measured SEE/delta pruning rather than reusing the rejected SEE-ordering policy;
- branching-factor / next-iteration time prediction;
- hot-path profiling and micro-optimization of move generation, make/unmake, TT, timing checks and evaluator calls.

Evidence rule: every meaningful search change is first checked for correctness and deterministic benchmark drift, then plays paired games against a frozen historical engine under equal resources. A mechanism is not retained merely because it is conventional or intuitively attractive.

Exit condition: strong, stable reference search and automated paired-game testing.

## M5 — Learned intelligence

- training data format/pipeline;
- a strong classical positional-evaluation control before neural replacement;
- experiment ladder from tiny scalar learned value to incremental sparse / king-relative features;
- incremental quantised evaluator;
- value head;
- legal-move policy head only after value cost is qualified;
- uncertainty calibration experiments;
- explicit measurement of inference/update latency, NPS, completed depth and equal-time Elo;
- native SIMD and WASM qualification.

Exit condition: learned evaluator beats the handcrafted reference under equal-time matches. Validation loss alone is not an acceptance metric.

## M6 — Strategic search and opponent-aware research

- bounded sparse node/edge arenas;
- strategic transposition identity;
- frontier scheduler;
- policy/uncertainty-directed work allocation;
- local tactical verifier integration;
- graph eviction/reuse experiments;
- opponent-response and fragility features within an objective safety envelope;
- synthetic search-ablation opponent populations, holdout validation and later online opponent inference.

The opponent-aware programme is specified in `docs/OPPONENT_EXPLOITATION.md` and ADR 0003. Objective search remains independently available and defines the safety envelope; opponent modelling may choose among safe moves but must not redefine chess truth.

Exit condition: strategic/opponent-aware variants beat the simpler objective reference across held-out populations and equal-resource matches, or are revised/removed.

## M7 — Parallel and browser engine

- coarse work scheduling;
- worker-local tactical state;
- contention/profiling suite;
- WebAssembly/Web Worker interface;
- WASM SIMD;
- bounded website difficulty/time profiles.

Exit condition: responsive browser play from the same engine core with measured native/WASM regressions.

## M8 — Website experience and analysis

- board UI and game flow;
- calibrated difficulty/personality profiles;
- live engine telemetry where useful;
- post-game analysis and principal variations;
- optional explanation layer grounded in engine analysis.

## Continuous — Strength laboratory

From M3 onward every release can be measured against fixed historical versions and external engines. The long-term target is not a claimed rating but a shrinking statistically measured Elo gap to top engines.
