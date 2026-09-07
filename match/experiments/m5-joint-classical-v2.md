# M5 joint classical evaluator v2

This experiment is the search qualification companion to `docs/M5_JOINT_CLASSICAL_V2.md`.

Baseline: `main@2a6172aaf460cc6c8c7811c4dc0c9e2ceed6205b`.

Reference evaluator: exact accepted E1+E4 classical evaluation with no experiment environment
variable. Reference deterministic search signature must remain `0x4c3bbe8701fbbb68` before games.

Candidate variants:

- `cp`: `CHESS_EXPERIMENTAL_CLASSICAL_V2=cp`, 100 paired games, seed `20261021`;
- `wdl`: `CHESS_EXPERIMENTAL_CLASSICAL_V2=wdl`, 100 paired games, seed `20261022`.

Both use the frozen UHO suite, Fastchess 1.8.2-alpha at
`f618e34540f94f4719ad3817950618dabe441318`, `1+0.01`, concurrency 1, Threads=1, Hash=32 MiB,
paired colour reversal, no ponder/tablebases/evaluation adjudication, max 300 moves.

No result in this file is an acceptance until a completed Actions artifact is recorded. A positive
100-game screen is only permission to run a fresh-seed 200-game marginal acceptance over the
strongest current production baseline.
