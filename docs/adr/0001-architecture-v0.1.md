# ADR 0001: Architecture v0.1

- Status: Accepted
- Date: 2026-09-06

## Context

The project aims to build a strong chess engine that is architecturally independent rather than a source-level reimplementation of an existing engine. The intended product also needs to run efficiently in a browser.

A fully persistent graph for every searched position is attractive conceptually but risks dominating runtime with allocation, memory bandwidth and synchronisation. Conversely, making a traditional depth-first alpha-beta tree the only organising abstraction would prematurely discard the policy/value/uncertainty and strategic-work-allocation experiments that motivate the project.

## Decision

Adopt a layered architecture with:

1. a small correctness-only chess core;
2. incremental learned evaluation as a replaceable layer;
3. a simple classical reference search;
4. a fast worker-local tactical alpha-beta/negamax verifier;
5. an experimental **sparse** persistent strategic DAG that retains selected useful positions rather than every tactical node;
6. a frontier scheduler that may allocate computation using learned policy, uncertainty, tactical signals and search bounds;
7. the same core/search implementation for native/UCI and WebAssembly targets.

All persistent search structures are bounded. Ordinary tactical traversal must not require persistent graph allocation.

## Consequences

Positive:

- distinct research direction without forbidding proven exact-search techniques;
- graph transpositions can be semantic at the strategic level;
- tactical calculation can remain extremely cheap and cache-friendly;
- browser memory can be bounded explicitly;
- experimental search can always be compared with a simpler baseline.

Costs/risks:

- two search timescales increase implementation complexity;
- strategic scheduling may fail to recover enough strength to justify overhead;
- policy/uncertainty inference may cost more than it saves;
- parallel graph coordination may become contentious.

These risks are accepted only as hypotheses. Equal-resource Elo testing is allowed to remove or substantially change the strategic DAG/scheduler while preserving the correctness, modularity, bounded-memory and measurement principles.
