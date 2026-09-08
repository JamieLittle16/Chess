# V14 capture-history A

Status: **rejected**

Hypothesis: improve V13's tactical/capture exactness by learning successful recursive capture beta
cutoffs and using a bounded `(moving piece, destination, captured piece)` history bonus for later
capture ordering. The candidate did not prune, extend, alter qsearch membership, change evaluation,
change LMR, or alter legality.

## Construction / safety gates

- exact final V13 BEST reconstructed and hash checked;
- `agent.py`, `numba_core.py`, and the residual file remained unchanged;
- competition API smoke passed;
- the candidate completed a paired fixed-node arena through the reusable V14 arena harness.

## Throughput

40 roots x 30,000 nodes x 3 repetitions:

- rep 0: 0.98508x V13 NPS;
- rep 1: 0.98699x;
- rep 2: 0.99524x;
- median: **0.98699x**, about 1.3% slower.

The bookkeeping is small but not actually free in full search.

## Discovery games

32 deterministic opening pairs, colour swapped, 16,000 fixed nodes/move:

- 64 games;
- candidate score: **30.0 / 64 = 46.875%**;
- naive Elo transform: **-21.74 Elo**.

Several pairs also produced asymmetric losses rather than merely transposed identical outcomes, so
the heuristic changed search in meaningful positions without producing a positive aggregate signal.

## Decision

Reject this exact capture-history policy. Do not tune the ordering scale or bonus constants on the
same opening slice. The result is negative enough that a parameter sweep would create an overfitting
risk without evidence that this context is the right abstraction.

This does not rule out tactical move-order improvements generally. Future work should use a
materially different signal (for example SEE-aware ordering, previous-ply tactical context, or a
learned/tactical correction) and must be tested from exact V13 or a later independently qualified
baseline.
