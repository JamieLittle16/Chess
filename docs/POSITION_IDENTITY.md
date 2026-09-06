# Position identity

Search needs compact identities for transpositions and repetition, but no hash is the authoritative chess state.

## Transposition-table Zobrist key

`Position` carries a deterministic 64-bit `ZobristKey` as a derived cache. It covers:

- every coloured piece/square pair;
- side to move;
- each castling right;
- the exact en-passant target square.

Halfmove and fullmove clocks are deliberately excluded. They are draw-rule context rather than move-graph identity. The transposition table therefore cannot decide rule-50 or repetition outcomes from its key alone.

The random-looking constants are generated at compile time from a fixed project seed with SplitMix64. There is no runtime RNG, generated source file, or platform-dependent initialization.

## Repetition identity is deliberately separate

Chess repetition equality is not quite the same as the conservative TT identity. An en-passant target only distinguishes repeated positions when the side to move actually has a **legal** en-passant capture. A FEN may therefore carry an en-passant target that should remain visible to the TT key while being irrelevant to repetition adjudication.

`Position::repetition_key()` derives the rule-correct repetition identity from the ordinary Zobrist key:

- piece placement, side to move and castling rights remain identical to TT identity;
- a genuinely legal en-passant capture keeps the en-passant component;
- an unusable or king-pinned en-passant target is removed from repetition identity.

The legality check is narrow: only the at-most-two candidate en-passant captures are examined. We do not generate the complete legal move list merely to canonicalise a repetition key.

Keeping two identities is intentional. Weakening the TT key to repetition semantics would merge more states than required; using the exact TT key for repetition would incorrectly distinguish positions whose unusable en-passant metadata has no legal effect.

## Draw context lives outside the TT key

`chess-engine` owns the sequence of repetition keys for actual game positions. `chess-search` receives the keys preceding its root and combines them with a fixed-size local search-path stack.

Draw adjudication happens before TT probing. In particular:

- threefold repetition counts prior game positions plus the current search path;
- the 50-move rule uses `Position::halfmove_clock()`;
- dead-material positions are recognized from canonical piece state;
- history-dependent draw scores are never stored as context-free exact TT entries.

This prevents a draw reached under one history from poisoning the same board reached under another history.

## Incremental maintenance

The ordinary TT key is maintained by the same primitive position mutators that maintain occupancy:

```text
place piece    -> XOR piece/square component
remove piece   -> XOR piece/square component
side change    -> XOR old/new side component
castling       -> XOR old/new rights components
en-passant     -> XOR old/new square component
```

XOR makes each update exactly reversible. `Undo` does not store the previous hash: unmake must reproduce it through the inverse state operations. Storing and restoring an old key would hide incremental hashing bugs.

## Reconstruction oracle

`Position::recomputed_zobrist_key` rebuilds the TT key from canonical board state. Structural invariant checks require:

```text
incremental key == recomputed key
```

This extends the two-path validation philosophy used by state transitions. Long legal playouts therefore check not only that pieces and metadata return exactly, but also that the derived search identity returns exactly.

## Collision policy

A 64-bit Zobrist key is a probabilistic cache identity, not a proof of equality. Search structures may use it in the conventional collision-tolerant way, but correctness-critical external interfaces continue to derive truth from canonical position state. If later graph nodes require stronger identity guarantees, the architecture permits a wider verification fingerprint or structural confirmation without changing the chess core's canonical representation.
