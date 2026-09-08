# V14 single-accumulator NNUE shadow cost

Status: **accepted as the leading V14 learned-evaluation runtime architecture**

This experiment maintains one absolute signed-piece-square `768 -> H` accumulator through exact V13
search but never consumes its score. The future student therefore predicts a White-perspective value
or correction and flips sign for Black-to-move, instead of carrying two perspective accumulators.

All widths passed:

- 5,000 incremental move transitions against full accumulator rebuild;
- 120/120 exact fixed-node V13 search signatures;
- unchanged V13 chess semantics because the shadow state is write-only.

Measured median full-search overhead before inference:

| Hidden | Candidate throughput fraction | Runtime overhead |
| ---: | ---: | ---: |
| 32 | 0.88765x | 12.66% |
| 48 | 0.92608x | 7.98% |
| 64 | **0.93535x** | **6.91%** |
| 96 | 0.91918x | 8.79% |
| 128 | 0.87769x | 13.94% |

For comparison, the qualified dual-perspective Chess768 shadow costs were approximately 17.42%,
20.16%, 22.06%, and 27.40% at H64/H96/H128/H192 respectively. The single representation therefore
cuts the H64 transport tax by roughly ten percentage points and makes H96 cheaper than dual H64.

## Decision

Use **H64 and H96** for the first quality-vs-speed training screen. H64 is the runtime sweet spot;
H96 is close enough in cost to justify testing whether the extra capacity buys meaningfully better
teacher fit and games.

Do not train or integrate the older dual-perspective V14-A architecture unless new evidence changes
this cost result. Do not use NumPy slice copies for accumulator transport; that experiment increased
overhead dramatically. Keep explicit scalar transport in the Numba hot path.
