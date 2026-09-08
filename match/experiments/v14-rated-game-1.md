# V14 rated-game regression 1 — prophylaxis / king-ray exposure

Status: **verified V13 failure / permanent diagnostic**

Position before V13's decisive 23.f3??:

```text
2r3k1/4qp2/4b3/p5p1/4P1P1/2Pr2P1/P4PB1/R1Q2RK1 w - - 1 23
```

The original postmortem reported Stockfish 16 at 250k nodes preferring 23.Rb1 and estimated roughly a
229cp one-move loss after f3.  The V14 lab independently reproduced the best move with pinned Stockfish
19 at 300,000 nodes: **Rb1 (`a1b1`)**, teacher score approximately +0.13 for White.

Exact V13 BEST fixed-node behavior:

| Budget | V13 move | V13 internal score |
| ---: | --- | ---: |
| 1,000 | Qc2 | +2.38 |
| 3,000 | Qc2 | +2.38 |
| 10,000 | Qb1 | +2.30 |
| 30,000 | Qb1 | +2.20 |
| 100,000 | Qb1 | +2.20 |
| 300,000 | **f3** | +2.13 |
| 1,000,000 | **f3** | +2.11 |

V13 never selected Rb1 over the 1k-1M node curve.  Increasing search effort therefore does not repair
the failure; deeper search actually stabilizes on f3 while the engine remains about two pawns too
optimistic.

The concrete tactical mechanism is long-range opponent activity: moving f2-f3 opens the
c5-d4-e3-f2-g1 diagonal, enabling ...Qc5+ while Black's rook is already deeply active on d3.

This fixture is a diagnostic, not a one-position optimization target.  A V14 mechanism may receive
credit for reducing teacher loss here only if it also survives broad regression and paired-game gates.
