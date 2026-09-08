V14 live experimental notes, 2026-09-08

Immutable chess control: exact Little Gambit V13 BEST.
Regression-lab branch is tooling/documentation only; it does not change the reconstructed engine.

Current candidates requiring additional evidence:
- H64 single-accumulator residual at 1/12: positive 40-game unseen-root equal-node discovery; needs fresh replication and equal-time.
- root-qsearch quiet slider checks: newly launched, motivated by verified rated-game prophylaxis failure.

Rejected/inert:
- main quiet history A
- capture history A
- precomputed slider rays
- dual NNUE slice-copy transport
- cheap defended-capture SEE B1-B4
- conservative IIR I1-I4
