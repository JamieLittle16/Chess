# Slider ray clipping v1

Status: **candidate / semantics-preserving performance optimization**

## Purpose

The accepted attack layer already precomputes occupancy-independent pawn/knight/king masks, but bishop and rook attacks still step square-by-square with coordinate arithmetic and bounds checks on every query.

V1 precomputes the four rays for every bishop and rook origin at compile time. Runtime attack generation intersects each ray with occupancy, finds the nearest blocker with one bit scan, and removes the blocker ray suffix. The blocker square itself remains included, preserving ordinary slider attack semantics.

Queen attacks remain the union of bishop and rook attacks.

## Correctness contract

This change is not allowed to alter chess or search semantics.

The branch adds deterministic differential coverage for every origin square across 512 pseudo-random occupancy masks plus empty/full occupancy, comparing the production ray-clipping implementation to an independent coordinate-walking reference. Existing move generation, perft, make/unmake, attack-query, search and reference-signature tests remain authoritative.

Acceptance requires exact preservation of:

```text
reference-search-v6
0xed4d9e0addb78419
```

Any score, node, TT-hit or best-move drift rejects the candidate.

## Performance rationale

The old path performs coordinate arithmetic, range checks and blocker tests once per traversed square. V1 performs four precomputed ray loads, four occupancy intersections and at most one nearest-bit scan per occupied direction. It is portable Rust with no BMI2/PEXT requirement, preserving the WASM-friendly architecture.

This optimization becomes more valuable as evaluation begins querying slider mobility. Wall-clock/NPS effects remain a separate measurement from semantic qualification.
