# Architecture

Status: **v0.2 — operational reference-engine contract**

This document records the architecture we intend to preserve while the implementation changes. Details marked **research hypothesis** must prove themselves empirically; they are not protected merely because they are novel.

## 1. Goals

The engine has four simultaneous goals:

1. correct chess;
2. very high native performance;
3. a first-class WebAssembly deployment for interactive play on the website;
4. an experimental search/evaluation architecture capable of becoming genuinely strong.

Strength and simplicity are allowed to overrule novelty. We are not implementing a disguised Stockfish clone, but neither do we reject a sound technique because another engine uses it.

## 2. Dependency direction

The implemented runtime dependency graph is one-way:

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

The future WASM frontend branches from the engine/search boundary rather than duplicating chess rules. Training, arena, and benchmark tooling sit outside the runtime engine and consume public interfaces; `tools/chess-bench` is the first implemented example.

Browser, UCI, filesystem, thread-pool, benchmark, and training concerns must not leak into `chess-core`.

Crates are introduced when they own real behaviour. We avoid creating empty abstraction layers in advance.

## 3. Chess core

`chess-core` owns facts of chess, not engine opinions:

- squares, colours, pieces and compact moves;
- bitboards and attack geometry;
- complete position state;
- legal move generation;
- make/unmake and reversible deltas;
- castling, en-passant, promotion and terminal-rule mechanics;
- Zobrist position identity.

### Hot-path contract

Ordinary move generation, make/unmake and search traversal must not perform routine heap allocation. State mutation is centralised so redundant caches cannot silently diverge.

The implemented design is a compact mutable `Position` plus stack-local reversible `Undo`. An independent immutable transition remains available as a differential correctness oracle. Cloning full positions inside recursive search is not an accepted search strategy.

`unsafe` Rust is forbidden at workspace level initially. A future use requires an ADR containing the measured benefit, invariants, tests and a safe fallback/reference path where practical.

## 4. Evaluation

Evaluation is not part of chess correctness. The current `chess-eval` implementation is deliberately simple material scoring and exists as a transparent reference baseline.

The eventual learned evaluator remains derived and disposable. A move should update evaluation state from its small position delta rather than reconstructing the entire neural input. The target neural interface produces at least:

- **value** — expected position quality;
- **policy** — relative usefulness of currently legal moves;
- **uncertainty** — a calibrated signal that may help allocate search effort.

The precise network topology is deliberately not frozen. CPU inference must remain small, quantisable and SIMD-friendly; browser inference is a first-class budget.

## 5. Search architecture

### 5.1 Implemented stable reference: exact local calculation

The repository now contains a conventional reference search in `chess-search`:

- reversible negamax/alpha-beta;
- iterative deepening;
- deterministic move ordering;
- bounded direct-mapped transposition storage;
- exact/lower/upper TT bounds;
- mate-distance normalization across transposition ply.

This implementation is intentionally retained as a control group even after more advanced search exists. Chess contains forcing lines that must be calculated rather than merely judged, so a fast local alpha-beta-style tactical primitive also remains a likely component of the advanced architecture.

Using alpha-beta as an exact calculation primitive is not the same as freezing it as the whole long-term engine architecture.

### 5.2 Research hypothesis: sparse strategic DAG

The proposed strategic layer represents selected important positions as nodes and moves as edges. Transpositions between retained strategic states resolve to shared nodes.

Crucially, **not every tactical search position becomes a persistent graph object**. Tactical traversal may examine millions of ephemeral states and return only useful bounds/results to the sparse graph.

This avoids turning graph allocation, pointer chasing and synchronisation into the engine's dominant cost.

### 5.3 Research hypothesis: budget-directed frontier

Instead of treating nominal depth as the sole unit of progress, a frontier scheduler may allocate work according to signals such as:

- network policy;
- uncertainty;
- tactical volatility;
- current bounds;
- transposition information;
- visits/work already invested;
- expected value of additional information.

This hypothesis must beat simpler baselines under equal wall-clock resources. If it does not, it changes.

## 6. Engine orchestration and protocols

`chess-engine` owns persistent game position plus reusable search state. It is the boundary where search limits, time control and later worker orchestration belong.

`chess-uci` translates protocol text into engine operations. It resolves incoming coordinate moves against the legal move list rather than re-implementing move semantics. The first UCI implementation is deliberately synchronous and fixed-depth; interruptible timed search is the next orchestration boundary.

Protocol-specific strings, parsing and I/O are outside search hot paths.

## 7. Memory model

Persistent search memory is bounded explicitly. The intended categories are:

- strategic node/edge arenas;
- strategic transposition index;
- worker-local tactical transposition storage;
- evaluator/network storage;
- fixed search stacks and move buffers.

The current classical TT is bounded and allocated once per reusable `Searcher`. Strategic nodes should eventually live in contiguous arenas and be referenced by compact integer IDs where practical. We avoid individually allocated, reference-counted graph nodes in inner search paths.

## 8. Parallelism

Workers should own their tactical hot state. Shared strategic state is touched at coarse work boundaries rather than on every searched node.

The design preference is:

```text
shared scheduler / bounded strategic graph
              ↓
        coarse work item
              ↓
worker-local tactical calculation
              ↓
       compact result/update
```

This is intended to preserve cache locality and minimise locks/atomics. Exact concurrency mechanisms remain experimental and must be profiled. The current reference search is single-threaded; concurrency is not introduced merely to claim parallelism.

## 9. WebAssembly

The website is a target, not a fork. The same engine core is compiled for native and WASM.

Baseline web deployment:

- engine executes in a Web Worker so UI rendering never waits on search;
- single-worker mode is fully supported;
- WASM SIMD is exploited when available;
- memory and network size are explicitly budgeted;
- optional parallel search must degrade cleanly when browser threading is unavailable.

## 10. Reference search and measurement

The classical reference search provides:

- a correctness/debugging oracle;
- a stable Elo baseline once timed match infrastructure is complete;
- a way to isolate evaluation improvements from scheduler improvements;
- evidence when a more complex search mechanism genuinely helps.

`tools/chess-bench` sits outside the runtime dependency chain and produces a deterministic fixed-work search signature in CI. Wall-clock performance and Elo are measured separately on controlled resources.

## 11. Architectural invariants

1. Chess correctness is independent of learned intelligence.
2. No routine allocation in the core traversal hot path.
3. Make/unmake is exactly reversible and heavily tested.
4. Derived caches are updated through controlled mutation boundaries.
5. Persistent search state is sparse or otherwise explicitly bounded.
6. Tactical inner search is worker-local and synchronisation-light.
7. Neural outputs guide decisions but never define legal chess.
8. Search, evaluation, protocol and deployment remain replaceable at explicit boundaries.
9. Native and WASM share the chess/search implementation.
10. Benchmarks and Elo, not intuition, decide performance-sensitive research hypotheses.
11. Tooling such as benchmarks and arenas consumes runtime APIs; it does not become a runtime dependency.

## 12. What is deliberately not frozen

- exact bitboard attack-generation technique;
- neural topology and feature representation;
- strategic priority formula;
- graph replacement/eviction policy;
- tactical pruning details;
- thread scheduling implementation;
- classical TT replacement policy/size;
- whether some or all strategic graph ideas survive strength testing.

Freezing these before measurement would turn architecture into dogma.
