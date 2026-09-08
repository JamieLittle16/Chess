# V14 cheap defended-capture ordering B

Status: **rejected**

This experiment attempted to retain the promising equal-node signal from bounded recursive SEE-A
while recovering its ~20% NPS cost.  Instead of evaluating an exchange sequence, B1-B4 demoted selected
adverse-MVV captures when the destination was cheaply detected as defended.  The heuristic was
restricted to main-search/root ordering; qsearch remained V13.

## Results

All four variants passed API/order-purity gates and completed 24 colour-swapped opening pairs at
14,000 fixed nodes/move.

| Variant | Score | Naive Elo | Median NPS vs V13 | Broad 12k moves changed |
| --- | ---: | ---: | ---: | ---: |
| B1 | 23.5/48 (48.96%) | -7.2 | 0.9649x | 23/48 |
| B2 | 24.0/48 (50.00%) | 0.0 | 0.9508x | 22/48 |
| B3 | 24.0/48 (50.00%) | 0.0 | 0.9632x | 23/48 |
| B4 | 25.0/48 (52.08%) | +14.5 | 0.9244x | 20/48 |

The original recursive SEE-A discovery scored 35.5/64 = 55.5% at equal nodes but only ~0.795x V13
NPS.  B1-B4 recovered much of the runtime but not that chess signal.

## Decision

Reject all B variants; do not tune thresholds on this opening slice.  The evidence suggests that
`destination defended?` is too lossy a proxy for the exchange information that helped SEE-A.  If SEE
is revisited, optimize a materially faithful exchange representation/cache rather than weakening the
chess question further.
