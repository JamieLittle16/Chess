# M5 joint classical v2 CP equal-nodes isolation

## Purpose

The equal-time v2 CP residual screen was positive despite a large throughput penalty. This experiment isolates chess signal from evaluator cost by giving the accepted classical reference and the exact frozen CP residual candidate the same 25,000-node budget per move.

This is diagnostic only. A positive equal-node result does not qualify the evaluator for production; it decides whether optimization/caching of the evaluator is a high-value next step.

## Frozen source

- candidate source predecessor: `23799f360aa99d91a811afdeb707b949e8679d09`
- evaluator variant: `CHESS_EXPERIMENTAL_CLASSICAL_V2=cp`
- reference evaluator: environment variable unset
- both launchers execute the same release binary
- accepted reference benchmark signature: `0x4c3bbe8701fbbb68`

## Match protocol

- Fastchess 1.8.2-alpha commit `f618e34540f94f4719ad3817950618dabe441318`
- 100 games, paired colour reversal
- 25,000 nodes per move for both engines
- Hash=32 MiB
- concurrency 1
- frozen `m3-uho-lichess-100-v1` opening suite
- seed `20261023`
- no evaluation adjudication or tablebases
- max 300 moves

## Decision rule

If the equal-node result is materially stronger than the equal-time result, treat evaluator runtime cost as the principal bottleneck and optimize the feature extractor before retesting equal-time strength. If the equal-node result is only small or neutral, do not spend a large engineering budget optimizing this evaluator family.
