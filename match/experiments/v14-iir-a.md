# V14 internal iterative reduction A

Status: **rejected / inert under tested conditions**

Four conservative IIR conditions were screened from exact V13.  All candidates were intended to
reduce nominal depth by one only at sufficiently deep nodes without a useful TT move.

## Results

All four completed 24 colour-swapped opening pairs at fixed nodes and the broad/seed probes.

| Variant | Score | Median NPS vs V13 | Broad moves changed | Seed moves changed |
| --- | ---: | ---: | ---: | ---: |
| I1 | 24/48 | 0.9926x | 0/48 | 0 |
| I2 | 24/48 | 1.0011x | 0/48 | 0 |
| I3 | 24/48 | 0.9737x | 0/48 | 0 |
| I4 | 24/48 | 0.9975x | 0/48 | 0 |

The exact 50% paired results and zero probe changes show that the conservative conditions are
functionally inert on this V13 test distribution.  Do not make IIR more aggressive merely to force a
behavioral difference; that would be a new hypothesis requiring independent motivation.
