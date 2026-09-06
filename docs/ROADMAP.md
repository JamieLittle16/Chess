# Roadmap

The roadmap is ordered by dependency and evidence, not by visual excitement.

## Current status

- **M0 complete** — core representation, toolchain and CI are green.
- **M1 complete** — legal chess and reference perft are green.
- **M2 complete** — reversible state and deterministic position identity are green.
- **M3 in progress** — the classical reference engine, deterministic benchmark, cooperative search limits and synchronous UCI path are operational; asynchronous stop/clock allocation and reproducible match qualification remain.

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

## M3 — Classical reference engine — in progress

Implemented:

- transparent material baseline evaluator;
- negamax + alpha-beta;
- deterministic move ordering;
- iterative deepening;
- bounded transposition table;
- persistent engine orchestration;
- generic cooperative cancellation in search;
- depth, node and movetime limits owned by engine orchestration;
- synchronous UCI target with FEN/startpos and `go depth` / `go nodes` / `go movetime` constraints;
- versioned deterministic reference-search benchmark/signature in CI.

Remaining before M3 exit:

- asynchronous UCI worker boundary so `stop` can interrupt a live search;
- full clock allocation (`wtime`, `btime`, increments, moves-to-go) and `go infinite` semantics;
- automated match harness integration;
- first reproducible baseline Elo under a documented protocol.

Exit condition: a correctly timed UCI engine with a reproducible baseline Elo.

## M4 — Tactical engine

- quiescence/forcing search;
- stronger move ordering;
- bounded tactical TT refinements;
- carefully measured pruning/reduction mechanisms;
- production time management.

Exit condition: strong, stable reference search and automated paired-game testing.

## M5 — Learned intelligence

- training data format/pipeline;
- incremental quantised evaluator;
- value head;
- legal-move policy head;
- uncertainty calibration experiments;
- native SIMD and WASM qualification.

Exit condition: learned evaluator beats the handcrafted reference under equal-time matches.

## M6 — Strategic search research

- bounded sparse node/edge arenas;
- strategic transposition identity;
- frontier scheduler;
- policy/uncertainty-directed work allocation;
- local tactical verifier integration;
- graph eviction/reuse experiments.

Exit condition: graph/search variants beat the simpler reference across short and long time controls, or are revised/removed.

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
