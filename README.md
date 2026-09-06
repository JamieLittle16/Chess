# Chess

A from-scratch, high-performance chess engine built around a deliberately modular architecture: a correctness-first chess core, incremental learned intelligence, sparse strategic search, and fast local tactical verification.

The project has two equal goals:

1. **Strength** — every search and evaluation idea must ultimately justify itself with reproducible performance and Elo testing.
2. **Architecture** — native, UCI, training, benchmarking, and WebAssembly targets share one engine core without browser or protocol concerns leaking into chess logic.

The architecture is documented before it is optimised. See `docs/` as the implementation grows.
