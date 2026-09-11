# V16 Hyperstition evaluator qualification

This document records the evidence behind the V16 Hyperstition evaluator experiment. It is an evaluator-lab record, not a release-Elo claim.

## Exact network identity

- Viridithas network release: `v92`
- Asset: `hyperstition-b400.nnue.zst`
- Compressed bytes: `22,895,545`
- Compressed SHA-256: `5b4045557ae14c2c89001bdb4dde84ff0bb5b24bbeb79632f868108e56a24c6f`
- Decompressed bytes: `50,616,896`
- Decompressed SHA-256: `36bcc6b3354ecbdb88fb95a341e494558b052223143f38ff6e6387aed99ab193`
- Reference implementation: Viridithas v14.0.1 commit `e066da52d614df515e046cd03afb598e1e8d791a`

## Correctness gates

The Little Gambit scalar oracle has exact raw-evaluation parity with the pinned Viridithas reference across the certification set. The reference is compiled for `x86-64-v3` so that the old v14 source takes its mature AVX2 path rather than an AVX-512/VNNI wrapper branch that does not compile cleanly under the current Rust toolchain.

The incremental accumulator is separately certified against full rebuilds. The real v92 network passed a 384-push/384-pop legal-move round trip, and explicit castling, en-passant, promotion, and king-feature-bucket transition cases. After every transition the incremental evaluation matched a fresh full rebuild, and unmake restored the prior state exactly.

## Initial equal-node strength screen

Against production Gestalt v85 with V15 search semantics unchanged except for evaluator substitution:

- 100 paired games at 25,000 nodes per move
- Hyperstition: 27 wins, 62 draws, 11 losses
- Score: 58.0%
- Screening estimate: approximately +56 Elo
- LOS reported by the qualification harness: 99.74%

This sample is encouraging but not sufficient for promotion. Equal-time testing is required because Hyperstition has a different inference cost.

## Safe AVX2 L1 qualification

The first scalar sparse-L1 experiment was rejected: it preserved scores but slowed the evaluator tail from roughly 2.314 microseconds to 4.698 microseconds per evaluation.

The accepted optimization keeps the workspace-wide `unsafe_code = "forbid"` contract and uses `safe_arch = "=1.2.0"` for the AVX2 packed arithmetic. On `x86-64-v3`, the L1 path consumes the network's native four-input interleaved layout with the same packed `u8 x i8` saturating multiply-add structure used by the pinned Viridithas implementation. Portable non-AVX2 builds retain the certified scalar layout.

Five paired evaluator-tail timing rounds produced:

- Scalar baseline ns/eval: `[2338.036, 2333.907, 2332.425, 2349.090, 2362.582]`
- Safe-AVX2 ns/eval: `[799.369, 800.778, 830.158, 795.176, 796.024]`
- Scalar median: `2338.036 ns/eval`
- Safe-AVX2 median: `799.369 ns/eval`
- Speedup: `2.9249x`
- Tail-time reduction: `65.810%`

The benchmark score vector was exactly unchanged: `[71, -322, 1215, 235, -160, -1166]`, with matching checksums. Additional standalone edge-regime FENs also matched exactly.

The qualified AVX2 implementation was materialized in commit `4c5dcd74cdf5fe1c855068b59f02a31cd853c5f1`.

## Promotion rule

Do not promote Hyperstition on equal-node evidence alone. The next decisive gate is a paired equal-time Hyperstition-v92 versus Gestalt-v85 match with both engines compiled under identical CPU flags and otherwise identical V15 search semantics. If that remains convincingly positive, increase the game count before production integration and then stack independently qualified search-speed improvements such as the TT static-evaluation cache.
