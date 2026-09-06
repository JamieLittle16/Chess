# State-transition architecture

The engine intentionally maintains two implementations of position transitions.

## 1. Reference transition

`Position::reference_after` is the executable correctness specification.

It clones canonical position state, applies one move in straightforward semantic code, and returns the resulting position. It is deliberately too expensive for competitive search. Its purpose is independence and debuggability.

## 2. Reversible engine transition

`Position::make_move` mutates one position in place and returns a fixed-size `Undo` record. `Position::unmake_move` restores the exact previous state from the move plus that record.

The undo record stores only information destroyed by the forward transition:

- captured piece and capture square, when present;
- previous castling rights;
- previous en-passant target;
- previous halfmove clock;
- previous fullmove number.

The moving piece does not need to be stored: ordinary moves recover it from the destination square, promotions restore a pawn, and castling geometry identifies the king and rook.

## Contract

`make_move` accepts a move produced by `Position::legal_moves`. It does not regenerate legal moves or redo king-safety validation. Search must never pay twice for a legality decision it already made.

In debug builds, strong assertions check semantic assumptions and structural bitboard invariants. Release builds keep the hot path small.

## Differential validation

Every optimized transition must remain testable against the reference implementation:

```text
canonical position P
        |
        +-- reference_after(m) --> expected P'
        |
        +-- make_move(m) --------> actual P'
                                    |
                                    +-- unmake_move(m, undo) --> P
```

Tests cover every legal move from representative positions containing castling, en-passant, captures, promotions, and ordinary moves. Deterministic long playouts compare every forward step with the reference implementation and then unwind the complete history to the original position.

This separation is permanent. Future incremental Zobrist keys and neural accumulators will be validated by the same pattern: optimized deltas must equal values reconstructed from canonical state.

## Intentional duplication

Some move semantics appear in both transition paths. That is intentional rather than accidental infrastructure duplication. If the optimized transition simply called the reference implementation internally, differential testing would cease to provide an independent check. Shared low-level board primitives remain canonical; transition mechanics remain separately testable.
