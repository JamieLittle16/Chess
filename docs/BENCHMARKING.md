# Benchmarking and Strength Testing

Performance and chess strength are separate measurements. A faster benchmark is not automatically a stronger engine, and an Elo result is meaningless without a documented test protocol.

## 1. Correctness gate

Before speed or Elo matters:

- unit tests cover value types and state invariants;
- make/unmake round trips restore every bit of position state;
- legal move generation is checked using published perft positions and counts;
- random legal sequences are unmade back to the initial state;
- optimised algorithms are cross-checked against simple reference implementations where practical;
- repetition, move-count and dead-material draw semantics are tested independently of the TT;
- protocol move sequences preserve game history transactionally.

Perft is a correctness tool, not an Elo benchmark.

## 2. Deterministic engine benchmark

The repository contains `tools/chess-bench`. The current draw-aware suite is `reference-search-v2` and pins:

```text
0x1a149495c23a7d8e
```

Each case starts from a repository-owned FEN, creates cold search state, and runs deterministic iterative deepening to a fixed depth. The report records:

- final score;
- searched nodes;
- transposition-table hits;
- encoded best move;
- one deterministic 64-bit signature over the complete suite result.

CI runs:

```sh
cargo run --release --quiet -p chess-bench
```

and prints the complete report/signature after the normal formatting, Clippy and test gates.

### V1 → V2 review

Adding rule-correct draw termination intentionally changed the deterministic search shape. The change was reviewed per-case before accepting a new signature:

- startpos: unchanged;
- Kiwipete: unchanged;
- mate-net: unchanged;
- en-passant: unchanged;
- promotion: score and best move unchanged, but dead-material continuations terminate earlier (`24 → 22` nodes, `8 → 6` TT hits).

The benchmark assertion now prints the complete case report when the signature drifts. A future change must therefore be inspected at the case level rather than updating an opaque hash by reflex.

### What the CI signature means

The signature is a **behavior/search-shape regression marker**, not a strength score. A change in evaluator, move ordering, pruning, TT behavior, draw semantics or search may legitimately change it. Such a change must be understood and the benchmark baseline updated deliberately rather than being treated as automatically bad.

Wall-clock thresholds are intentionally **not** enforced on shared CI runners. Timing claims require controlled hardware. CI establishes deterministic behavior; local/dedicated benchmark machines establish speed.

As the architecture grows, the benchmark report will add relevant counters, for example tactical nodes, strategic expansions, neural evaluations, graph hits/transposition merges and memory high-water marks.

Node counts from different engine architectures are **not** directly comparable. Equal wall-clock strength is the important cross-engine metric.

## 3. Microbenchmarks

Hot components are measured independently when optimisation work begins:

- move generation;
- make/unmake;
- attack generation;
- hashing/repetition identity;
- evaluator push/pop and inference;
- tactical TT probing;
- strategic table lookup.

Record CPU, compiler/toolchain, build flags and benchmark corpus. Optimisations must not silently weaken correctness checks.

## 4. Elo testing

The engine exposes UCI so an established match runner such as Fastchess can test it under controlled conditions. The match runner is measurement infrastructure: it must not become coupled to search internals.

The repository-owned wrapper and lifecycle contract are specified in [`MATCH_QUALIFICATION.md`](MATCH_QUALIFICATION.md). The first finite-time protocol is `match/protocols/m3-baseline-v1.json`; it is deliberately conservative and records exact input/output hashes rather than treating a terminal score line as sufficient evidence.

### Paired-game protocol

For candidate `C` against reference `R`:

1. use the same physical machine/CPU allocation;
2. fix threads, memory, tablebase access and ponder policy;
3. use the same time control and adjudication rules;
4. select openings from a versioned opening suite;
5. play each opening twice with colours reversed;
6. retain paired (pentanomial) outcomes rather than only aggregate W/D/L;
7. retain raw runner output/PGN and exact engine revisions;
8. report Elo difference with uncertainty/confidence bounds and the complete protocol.

Typical result form:

```text
candidate:  search-frontier-v7@<sha>
reference:  main@<sha>
games:      20,000 (10,000 pairs)
time:       <protocol>
openings:   <suite + hash>
elo:        +4.8
95% CI:     [+1.6, +8.0]
```

Numbers without the protocol are not accepted as evidence.

The immediate M3 qualification task is now narrower: freeze the opening suite and obtain the first retained external baseline through the checked-in harness. That result will be a **relative engine Elo under the named protocol**, not an absolute human rating.

## 5. SPRT development tests

For high-volume search tuning we intend to support sequential probability ratio tests (SPRT), allowing a candidate to be accepted/rejected once evidence crosses predeclared bounds rather than choosing a favourable stopping point after looking at results.

Short-time-control tests are useful for throughput during development. Important changes should also receive longer-time-control validation because search architecture can scale differently with thinking time.

## 6. External engine comparison

To measure the gap to Stockfish or another engine, use identical resource constraints and a paired opening protocol. Report **relative Elo under that protocol**, for example:

```text
OurEngine 0.7 vs Stockfish X
Delta: -240 Elo ± 12 (95% CI)
```

This is a real experimental statement. It is not the same as claiming an absolute FIDE rating.

A separate multi-engine ladder may provide an internally anchored engine rating scale, but every published rating must name the pool and protocol.

## 7. Browser qualification

WASM has separate product constraints. Record on representative browsers/hardware:

- module/network size;
- startup time;
- memory high-water mark;
- positions/search work per second;
- move latency at each website difficulty;
- UI responsiveness (search remains off the main thread).

Native and browser strength should share algorithms while allowing explicitly documented resource budgets.
