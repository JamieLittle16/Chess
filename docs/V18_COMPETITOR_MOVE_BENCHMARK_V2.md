# V18 competitor move benchmark — V2 oracle correction

**V2 is the authoritative scoring protocol.** Use
`scripts/v18_competitor_move_benchmark_v2.py` and
`scripts/v18_competitor_benchmark_gate_v2.py` for new results.

The corpus selection, phase balancing, competition-clock reconstruction and candidate-state reset are
unchanged from the original benchmark. V2 changes only how Stockfish scores the moves.

## Why V2 exists

The first implementation used an unrestricted fixed-node Stockfish search both to discover its best
move and as the numeric score baseline, then compared that score with separate root-restricted
fixed-node searches of the historical and candidate moves.

That is not quite apples-to-apples. An unrestricted search spreads nodes over multiple roots while a
root-restricted search spends its full budget below one root. On a small number of positions the
restricted historical root therefore scored above the unrestricted 'best' score. Clipping negative CPL
to zero hid part of the direct candidate-vs-historical difference.

The original **pairwise historical-vs-candidate root score** was still a useful diagnostic because
both sides received equal root-restricted budgets. The old CPL totals should nevertheless be treated
as preliminary rather than certification evidence.

## V2 Stockfish protocol

For each selected position V2 performs:

1. one unrestricted fixed-node search to **discover** Stockfish's preferred root move;
2. one equal-node root-restricted search of that discovered move;
3. one equal-node root-restricted search of the historical opponent move, unless it is the discovered
   move and can reuse step 2;
4. one equal-node root-restricted search of Little Gambit's move, unless it can reuse an existing
   root result.

All numeric move comparisons therefore come from equal-budget root-restricted searches.

The shared score reference is the maximum score among the discovered-best root, historical root and
candidate root. Consequently:

```text
historical CPL - candidate CPL
    == candidate root score - historical root score
```

for every legal candidate move. A candidate that causes Stockfish to prefer it over the discovery
move is allowed to establish the reference rather than being clipped away.

Stockfish-best-move agreement remains a secondary metric; it uses the unrestricted discovery move.
The primary competitive metrics are direct root-score delta, WDL-expectation delta, CPL reduction and
the 8 cp pairwise win/tie/loss score.

## Gates

The per-engine regression gate remains:

- zero illegal moves;
- mean CPL no worse than the historical opponent;
- mean WDL-expectation loss no worse;
- pairwise score at least 50%;
- no increase in >=80 cp mistakes;
- no excess of >=80 cp regressions over >=80 cp gains.

The eight-engine V2 outperformance gate additionally requires, for **every** panel engine, at least a
0.5 cp mean CPL improvement, pairwise score strictly above 50%, Stockfish-best agreement no worse and
>=80 cp mistakes no worse.

A static V2 pass is a development/accuracy gate, not an Elo proof. Promotion still requires paired
real-clock games under the Chessathon 120+0.5 environment.
