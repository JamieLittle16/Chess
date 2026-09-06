# Position identity

Search needs a compact identity for transpositions, but a hash must never become the authoritative chess state.

## Zobrist key

`Position` carries a deterministic 64-bit `ZobristKey` as a derived cache. It covers:

- every coloured piece/square pair;
- side to move;
- each castling right;
- the exact en-passant target square.

Halfmove and fullmove clocks are deliberately excluded. They are search/draw-rule context rather than move-graph identity. A future transposition table must therefore handle rule-50/repetition information separately instead of assuming that a matching Zobrist key alone settles draw semantics.

The random-looking constants are generated at compile time from a fixed project seed with SplitMix64. There is no runtime RNG, generated source file, or platform-dependent initialization.

## Incremental maintenance

The same primitive position mutators that maintain occupancy also maintain the key:

```text
place piece    -> XOR piece/square component
remove piece   -> XOR piece/square component
side change    -> XOR old/new side component
castling       -> XOR old/new rights components
en-passant     -> XOR old/new square component
```

XOR makes each update exactly reversible. `Undo` does not store the previous hash: unmake must reproduce it through the inverse state operations. Storing and restoring an old key would hide incremental hashing bugs.

## Reconstruction oracle

`Position::recomputed_zobrist_key` rebuilds the key from canonical board state. Structural invariant checks require:

```text
incremental key == recomputed key
```

This extends the two-path validation philosophy used by state transitions. Long legal playouts therefore check not only that pieces and metadata return exactly, but also that the derived search identity returns exactly.

## Collision policy

A 64-bit Zobrist key is a probabilistic cache identity, not a proof of equality. Search structures may use it in the conventional collision-tolerant way, but correctness-critical external interfaces must continue to derive truth from canonical position state. If later graph nodes require stronger identity guarantees, the architecture permits a wider verification fingerprint or structural confirmation without changing the chess core's canonical representation.
