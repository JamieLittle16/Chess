# V14 one-layer quiet-check qsearch A

Status: **rejected**

Hypothesis: V13's rated `23.f3??` failure might be a forcing-horizon defect because normal qsearch
searches captures/promotions but not quiet checks. At qsearch entry only, the candidate therefore
retained legal quiet moves that give immediate check; all deeper qsearch plies remained V13-like.

## Rated-game sentinel

The candidate did **not** solve the failure. Against the verified position
`2r3k1/4qp2/4b3/p5p1/4P1P1/2Pr2P1/P4PB1/R1Q2RK1 w - - 1 23`:

- 10k: Qb1 (control Qb1)
- 30k: Qb1 (control Qb1)
- 100k: Qb1 (control Qb1)
- 300k: **f3** (control f3)
- 1,000k: **f3** (control f3)

Pinned Stockfish 19 prefers Rb1. The candidate's high-node score still remained about +2.1, so seeing
one quiet checking layer did not repair the underlying position valuation.

## Runtime

Median fixed-node NPS ratio: **0.8370x V13** (~16.3% slower).

## Equal-node games

24 colour-swapped opening pairs at 16k nodes/move:

- 48 games
- candidate score **23.5/48 = 48.96%**
- naive Elo transform **-7.2 Elo**

## Decision

Reject. The experiment strongly suggests the rated loss is not merely caused by omission of
`...Qc5+` from qsearch. The engine continues to value the resulting king/rook geometry too highly
after the forcing check is visible.

Next work should target prophylaxis/king danger and enemy penetration directly, preferably at the
root first so richer geometry can be tested without taxing every recursive node.
