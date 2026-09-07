# V14-A main quiet history

Status: **rejected**

This experiment tested a deliberately narrow main quiet-history heuristic on top of the exact
qualified Python V13 BEST engine. It changed recursive quiet ordering and rewarded quiet beta
cutoffs, while leaving the evaluator, qsearch, legality core, TT policy, pruning margins, LMR and
time management unchanged.

## Immutable control

The control is exact final V13 BEST from `analysis/v13-final-best-20260907` at
`b98735d0f9f0a48c0e2e47478bf6295ded286c3a`.

Final V13 component hashes were verified before every confirmation run. Search-only candidate
construction also proved `agent.py`, `numba_core.py`, and `v13_residual.i16` byte-identical to the
control.

## Evidence

| Stage | Protocol | Games | Candidate score | Naive Elo | Decision |
| --- | --- | ---: | ---: | ---: | --- |
| discovery | 12k fixed nodes/move, paired colours | 32 | 17.5/32 (54.69%) | +32.7 | investigate |
| fresh replication | 12k fixed nodes/move, disjoint openings 32:64, paired colours | 64 | 31/64 (48.44%) | -10.9 | failed replication |
| timed production A/B | `agent.get_move`, 2.5s + 0.05s, disjoint openings 64:80, paired colours | 32 | 17/32 (53.13%) | +21.7 | insufficient/noisy |

The timed test used an explicit test-only reset protocol between games so Numba code remained JIT
compiled while per-game mutable history, clock feedback, hash-move cache and TT state were cleared.
Mean observed move wall times were 65.36 ms for the candidate and 66.34 ms for the control, so the
result does not indicate a meaningful runtime regression or gain.

## Decision

Reject this exact candidate. The larger independent fixed-node replication reversed the discovery
signal, while the small timed result is compatible with noise and is not sufficient evidence to
merge a behavioural change into a strong qualified baseline.

Do **not** cite the discovery +32.7 Elo as an engine gain and do not stack continuation history,
correction history, or LMR changes on this implementation.

This does **not** reject modern history/correction search as a V14 architecture. It rejects the
specific side/from/to quiet-cutoff history policy tested here. Future history work must be a
materially different integrated hypothesis and must again be tested marginally against exact V13
(or a later independently qualified V14 baseline).
