# V14 Search-v2 candidate

V14 is the first search revision built on top of the production mature Gestalt evaluator and the accepted deferred-accumulator optimization.

## Goal

Recover the useful strength signal from the first main + continuation history experiment without its repeated quiet rescoring cost, then test whether history should also condition late-move reductions.

## Production baseline

- base commit: `f6ac75d644b844fabf35195d6054703e68bcc60f`
- evaluator: incremental Gestalt `gestalt-b840.nnue`
- accepted deferred accumulator update after late-quiet futility rejection

## Candidate A: once-scored history

- side-specific main quiet history
- one-ply continuation history
- bounded gravity updates
- quiet fail-high bonus and smaller fail-low malus at scout nodes
- each remaining quiet is history-scored exactly once when the quiet stage begins
- cached quiet tuples are ordered once and consumed linearly
- TT, tactical and killer stages remain ahead of ordinary quiets

The first M6 history probe showed an encouraging equal-node signal but repeatedly rescored all remaining quiets on every selection. V14 removes that selection architecture cost rather than weakening the heuristic.

## Candidate B: once-scored history + history-conditioned LMR

Candidate B adds a conservative reduction adjustment:

- strongly positive history can remove one ply of reduction;
- strongly negative history can add at most one ply of reduction at sufficiently deep/late nodes;
- the existing verification path remains intact, so a reduced alpha raise is still re-searched at full depth.

## Qualification

The research branch is dormant by default. The qualification workflow materializes each candidate from an exact patcher and compares it against the production baseline with:

- exact certified Gestalt network;
- frozen 5,000-root M6 UHO suite;
- paired colour reversal;
- 100 games per candidate;
- 25,000 nodes per move;
- Hash 32 MiB;
- concurrency 1;
- fixed deterministic seeds;
- candidate/reference timing extraction from PGN.

A production v14 promotion should only happen after a candidate shows convincing chess strength and acceptable wall-clock cost, followed by an equal-time production gate.
