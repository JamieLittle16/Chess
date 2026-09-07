# V14-A main quiet history — rejected

V14-A tested a deliberately narrow side/from/to main quiet-history table on top of the exact CI-qualified V13 control. The candidate changed ordinary quiet ordering only; evaluation, qsearch, legality, RFP/LQF, adaptive verified LMR v3, TT/draw semantics and time management were frozen.

## Mechanical qualification

The candidate passed:

- exact V13 reconstruction and component hash checks;
- recursive search-call arity validation;
- competition API legality smoke;
- deterministic fixed-node candidate reproducibility;
- fixed-node throughput guard;
- unchanged `numba_core.py` and learned residual.

## Strength results

Discovery, frozen first 16 openings, colour reversed, 12,000 nodes/move:

- 32 games
- candidate score: **17.5/32 = 54.6875%**
- naive score conversion: about **+32.7 Elo**

Fresh confirmation, disjoint openings 16–55, colour reversed, same 12,000 nodes/move and unchanged parameters:

- 80 games
- candidate score: **39.5/80 = 49.375%**
- naive score conversion: about **−4.3 Elo**

## Decision

**Reject V14-A. Do not merge or retune on these books.**

The positive discovery result failed fresh replication. This is exactly the selection-bias failure mode the V14 qualification discipline is intended to catch. A future integrated history/continuation/LMR architecture may still be worthwhile, but this particular standalone main-history implementation has not earned inclusion and must not be treated as an accepted V14 component.
