# Fixed leaper/pawn attack tables v1

Status: **candidate / semantics-preserving performance optimization**

## Purpose

Pawn, knight and king attack geometry is occupancy-independent. The baseline reconstructed these masks through coordinate loops on every call even though the answer depends only on the square (and colour for pawns).

V1 replaces that repeated work with compile-time 64-square lookup tables for:

- white pawn attacks;
- black pawn attacks;
- knight attacks;
- king attacks.

Slider attacks remain unchanged.

## Correctness contract

This change is not allowed to alter chess or search semantics.

The branch includes an exhaustive differential test over all 64 squares comparing the production tables against an independent coordinate-based reference for both pawn colours, knights and kings. Existing move-generation, perft, reversible-state and search tests remain authoritative.

After E1 became production at `main@5de2435540467db07f4b3bdb4ac2bfef890c792b`, final qualification must be performed against the `reference-search-v6` E1 baseline. The exact v6 scores, best moves, node counts, TT hits and signature `0xed4d9e0addb78419` must remain unchanged. Any deterministic search drift is a rejection, not a new baseline.

## Performance rationale

The table path is one indexed `u64` load plus the existing `Bitboard` wrapper. This removes repeated coordinate arithmetic, bounds checks and mask construction from move generation and attack queries, and also prepares a cheaper substrate for future mobility evaluation.

This experiment makes no Elo claim by itself. Wall-clock/NPS effects should be measured separately from shared-runner CI before stronger performance conclusions are recorded.
