# Fixed leaper/pawn attack tables v2

Status: **candidate / semantics-preserving performance optimization**

## Purpose

Pawn, knight and king attack geometry is occupancy-independent. The E1 baseline reconstructs these masks through coordinate loops on every call even though the answer depends only on the square (and colour for pawns).

V2 is rebased directly on production E1 (`main@5de2435540467db07f4b3bdb4ac2bfef890c792b`) and replaces that repeated work with compile-time 64-square lookup tables for:

- white pawn attacks;
- black pawn attacks;
- knight attacks;
- king attacks.

Slider attacks remain unchanged.

## Correctness contract

This change is not allowed to alter chess or search semantics.

The branch includes an exhaustive differential test over all 64 squares comparing the production tables against an independent coordinate-based reference for both pawn colours, knights and kings. Existing move-generation, perft, reversible-state and search tests remain authoritative.

The final qualification target is the current E1 deterministic baseline:

```text
reference-search-v6
0xed4d9e0addb78419
```

The exact v6 scores, best moves, node counts and TT hits must remain unchanged. Any deterministic search drift is a rejection, not a new baseline.

## Performance rationale

The table path is one indexed `u64` load plus the existing `Bitboard` wrapper. This removes repeated coordinate arithmetic, bounds checks and mask construction from move generation and attack queries, and prepares a cheaper substrate for future mobility evaluation.

This experiment makes no Elo claim by itself. Wall-clock/NPS effects should be measured separately from shared-runner CI before stronger performance conclusions are recorded.
