# Roadmap

The roadmap is ordered by dependency and evidence, not by visual excitement.

## Current status

- **M0 complete** — core representation, toolchain and CI are green.
- **M1 complete** — legal chess and reference perft are green.
- **M2 complete** — reversible state and deterministic position identity are green.
- **M3 complete** — the classical reference engine is timed, draw-correct, externally measurable and has retained Stockfish calibration infrastructure.
- **M4 in progress** — bounded quiescence, staged move picking, PVS, two-slot killer ordering, tapered geometric evaluation and E4 bishop-pair/rook-file structure are accepted. The engine also has a permanent strategic draw regression suite proving that wins avoid available draws and losses seek them. Conservative LMR v2 is the current live search-selectivity experiment on top of the E4 production baseline.

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
- UCI `Hash` sizing with production 32 MiB default while deterministic benchmark search remains entry-count pinned;
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
- reproducible tooling for creating disjoint holdout suites from the pinned multi-million-position UHO source;
- retained external calibration against a fixed Stockfish configuration.

The external calibration is a protocol-specific development result, not a FIDE rating. It predates substantial M4 strength gains and must be rerun before quoting a current absolute estimate.

`go infinite`, ponder and richer GUI-facing features remain useful compatibility work but are no longer M3 blockers. They can be added when selected harnesses/opponents require them.

Exit condition: a correctly timed, draw-correct UCI engine with a reproducible measured baseline. **Met.**

## M4 — Tactical and classical-strength engine — in progress

### Accepted production stack

- bounded four-qply quiescence with a specialized tactical-only legal generator;
- allocation-free staged `MovePicker` with lazy tactical selection and no global sort;
- principal variation search / null-window probing for later moves;
- tapered geometric PSQT evaluator (E1);
- two quiet killer slots per ply;
- portable compile-time leaper attack tables and clipped slider rays;
- production UCI `Hash` sizing;
- E4 bishop-pair and rook open/semi-open-file evaluation;
- strategic repetition/stalemate regressions as a permanent search contract.

Current production benchmark: `reference-search-v8`, signature `0x4c3b_be87_01fb_bb68`.

Important accepted paired-game evidence includes:

- qsearch v1 vs M3: `+281.68 +/- 58.17` Elo;
- staged MovePicker vs qsearch: `+74.06 +/- 37.99` Elo;
- PVS v1 vs staged MovePicker: `+41.89 +/- 30.29` Elo;
- E1 tapered PSQT vs material/PVS: 62W / 26D / 12L, `+190.85 +/- 64.16`, LOS 100%;
- two-slot killers vs E1 production: 63W / 94D / 43L, `+34.86 +/- 34.16`, LOS 97.83%;
- E4 fresh disjoint UHO holdout: 70W / 80D / 50L, `+34.86 +/- 35.54`, LOS 97.40%.

These are sequential development comparisons against different historical baselines. They are not additive absolute ratings.

### Rejected / non-production hypotheses

The project keeps negative results because avoiding repeated dead ends is part of the architecture:

- SEE ordering v1: negative screen;
- full quiet-history layered onto killers: no proven marginal value;
- generic pawn structure E3 over killers: old positive signal collapsed on stronger search;
- raw and pawn-safe mobility: no justified marginal gain on stronger search;
- one-slot countermove: neutral over killers;
- conservative null-move v1: draw-safe and correct, but neutral at equal time;
- four-way clustered TT: no gain at the 32 MiB production hash budget;
- compact king-zone attack-count safety E5: negative; future king-danger work must be materially smarter rather than coefficient retuning.

The canonical detailed status is `docs/M4_EXPERIMENT_LEDGER.md`.

### Current and next high-value work

1. **Conservative LMR v2** — current live experiment. The policy reduces only fourth-and-later quiet, non-checking moves by one ply at depth >=3 and verifies every reduced alpha improvement at full depth. It is being measured marginally over E4; no merge without clean materialization and acceptance.
2. **Aspiration windows** — next clean iterative-deepening search-speed experiment after the LMR baseline settles. Must use safe fail-low/fail-high widening and preserve the exact final root result.
3. **Qsearch selectivity v2** — investigate delta-style or tactical-specific pruning as a new hypothesis rather than reusing rejected SEE ordering. Tactical correctness and mate/check handling remain non-negotiable.
4. **Improved quiet ordering only when materially different** — e.g. a low-overhead continuation/history formulation justified by profiling; do not retry the rejected full-history/countermove designs unchanged.
5. **Null-move v2 only as a materially different policy** — the reversible/draw-isolation substrate from v1 is valid, but the conservative v1 gates earned no strength. Any revisit should change the hypothesis (adaptive reduction/verification/material gates), not simply retune constants.
6. **Futility / late-move pruning** — only after LMR/ordering establishes a sufficiently strong and stable selectivity baseline.
7. **Stronger king danger** — attacker-count thresholds, contact/check features, shelter/storm structure or shared cached attack features; do not retry the rejected all-attack-count E5 model.
8. **Hot-path profiling** — move generation, make/unmake, TT, timing checks and evaluator calls; semantics-neutral wins should stack with every future strength feature.
9. **Fresh external calibration** — rerun Stockfish calibration once the E4 + selectivity stack settles, rather than treating the old M3 calibration as current.

Evidence rule: every meaningful search/evaluation change is checked for correctness and deterministic benchmark drift, then plays paired games against a frozen historical engine under equal resources. A mechanism is not retained merely because it is conventional or intuitively attractive. If production advances while an experiment is running, a positive stale-baseline result must be re-tested marginally on the new production stack.

Exit condition: strong, stable reference search, automated paired-game/holdout qualification, and a classical engine strong enough to serve as the control for learned evaluation.

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
