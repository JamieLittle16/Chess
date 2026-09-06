# Roadmap

The roadmap is ordered by dependency and evidence, not by visual excitement.

## M0 — Core foundations (current)

- workspace/toolchain/CI;
- compact square, colour, piece and move domain types;
- bitboards;
- complete position storage shape;
- FEN parser;
- architecture, development and benchmark contracts.

Exit condition: CI clean and the representation invariants are tested.

## M1 — Legal chess

- leaper and sliding attacks;
- pseudo-legal generation;
- check/pin handling;
- fully legal move generation;
- castling, en-passant and promotions;
- published perft suite.

Exit condition: all selected reference perft positions agree through meaningful depths.

## M2 — Reversible state and identity

- compact make/unmake stack;
- `PositionDelta`/undo state;
- incremental occupancy/attack-derived state where justified;
- deterministic Zobrist hashing;
- random-play round-trip/property tests.

Exit condition: long random legal sequences unmake bit-exactly and hashes reproduce.

## M3 — Classical reference engine

- material/positional baseline evaluator;
- negamax + alpha-beta;
- iterative deepening;
- basic transposition table;
- UCI target;
- deterministic engine benchmark.

Exit condition: a correctly timed UCI engine with a reproducible baseline Elo.

## M4 — Tactical engine

- quiescence/forcing search;
- move ordering;
- bounded tactical TT;
- carefully measured pruning/reduction mechanisms;
- time management.

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
