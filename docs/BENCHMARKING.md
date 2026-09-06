# Benchmarking and Strength Testing

Performance and chess strength are separate measurements. A faster benchmark is not automatically a stronger engine, and an Elo result is meaningless without a documented test protocol.

## 1. Correctness gate

Before speed or Elo matters:

- unit tests cover value types and state invariants;
- make/unmake round trips restore every bit of position state;
- legal move generation is checked using published perft positions and counts;
- random legal sequences are unmade back to the initial state;
- optimised algorithms are cross-checked against simple reference implementations where practical.

Perft is a correctness tool, not an Elo benchmark.

## 2. Deterministic engine benchmark

We will add a stable `bench` command once search exists. A versioned suite of positions will run at deterministic limits and report at least:

- elapsed time;
- tactical nodes;
- strategic expansions;
- neural evaluations;
- transposition hits;
- graph hits/transposition merges;
- peak strategic memory;
- a deterministic result/signature suitable for regression detection.

Node counts from different engine architectures are **not** directly comparable. Equal wall-clock strength is the important cross-engine metric.

## 3. Microbenchmarks

Hot components are measured independently when optimisation work begins:

- move generation;
- make/unmake;
- attack generation;
- hashing;
- evaluator push/pop and inference;
- tactical TT probing;
- strategic table lookup.

Record CPU, compiler/toolchain, build flags and benchmark corpus. Optimisations must not silently weaken correctness checks.

## 4. Elo testing

The engine will expose UCI so established match runners such as Fastchess can test it under controlled conditions.

### Paired-game protocol

For candidate `C` against reference `R`:

1. use the same physical machine/CPU allocation;
2. fix threads, memory, tablebase access and ponder policy;
3. use the same time control and adjudication rules;
4. select openings from a versioned opening suite;
5. play each opening twice with colours reversed;
6. retain paired (pentanomial) outcomes rather than only aggregate W/D/L;
7. report Elo difference with uncertainty/confidence bounds and the complete protocol.

Typical result form:

```text
candidate:  search-frontier-v7
reference:  main@<sha>
games:      20,000 (10,000 pairs)
time:       <protocol>
elo:        +4.8
95% CI:     [+1.6, +8.0]
```

Numbers without the protocol are not accepted as evidence.

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
