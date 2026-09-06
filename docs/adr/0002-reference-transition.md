# ADR 0002: Preserve a simple reference transition

- **Status:** Accepted
- **Date:** 2026-09-06

## Context

A strong engine needs an extremely cheap reversible `make` / `unmake` path. That code will eventually update occupancy, castling state, en-passant state, clocks, Zobrist identity, attack-related caches, and neural accumulators incrementally. It is also one of the easiest places to introduce subtle state corruption.

Using the optimized transition as its own correctness oracle would make those bugs difficult to isolate.

## Decision

`chess-core` keeps a deliberately simple immutable transition, currently exposed as `Position::reference_after`.

The reference path:

- clones the persistent position;
- applies the move semantically in straightforward code;
- maintains only canonical chess state;
- checks structural cache invariants;
- is used by the first legal-move generator and reference perft implementation.

It is explicitly **not** the future search hot path.

M2 will introduce a separate reversible transition designed for speed. Tests will apply the same legal move through both implementations and require identical resulting canonical positions. Random legal playouts will extend that comparison over long move sequences and full undo chains.

## Consequences

### Positive

- Optimized state mutation has an independent oracle.
- Perft failures can initially be debugged against simple state semantics.
- Future Zobrist and neural incremental updates can be checked against reconstruction from canonical position state.
- We can optimize aggressively without making correctness depend on the optimized implementation.

### Cost

- Some move semantics exist in two implementations after M2.
- The reference path is intentionally too slow for competitive search.

That duplication is accepted because the two implementations serve different purposes: one is the specification executable, the other is the performance implementation.
