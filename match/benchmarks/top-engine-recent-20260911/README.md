# Recent top-engine move benchmark

This is an **offline research benchmark** built from the user's retained AI Chessathon PGNs on 11 September 2026. It is designed to answer a narrower question than self-play Elo testing:

> On positions actually faced by strong recent competitors, does the current Little Gambit candidate choose moves that Stockfish judges at least as strong as the moves those competitors played?

The source archive contained 46 PGN files. Exact duplicate PGN files were removed before freezing the corpus, leaving 37 unique games. The reconstructed PGN is content-addressed in `manifest.json`.

## Benchmark targets

The default CI matrix scores the three principal strong opponents represented repeatedly in the retained set:

- Ryan Vincent
- Emile Andrieu
- Lightning Tree

The runner accepts any exact PGN player name via `--target`, so the suite can be extended to other opponents without changing its methodology.

## Position selection

For each target, the runner extracts every position immediately before that target moved and records the historical move. Duplicate FENs are collapsed so repeated games/opening downloads do not overweight the same decision. Up to 48 positions are then selected deterministically with balanced coverage of early/opening, middlegame and endgame positions.

Selection is independent of the candidate engine's output. This matters: changing Little Gambit cannot change which positions it is tested on.

The candidate receives the exact FEN and the best reconstruction of the target's **pre-move competition clock**. PGN `%clk` comments report post-move clocks, so the next move's pre-clock is the same side's previous `%clk`; each side's first move starts from the competition's 120-second base.

Every static position starts with Little Gambit's known TT/history/game state cleared. This prevents one benchmark position from leaking search information into another. Consequently, this is a move-choice accuracy test rather than a simulation of a continuous game.

## Stockfish oracle

Stockfish 19 runs at full strength, one thread, a fixed hash size and an equal fixed-node budget for each root query. For every position it performs:

1. an unrestricted search to establish the best root score and best move;
2. a root-restricted search of the historical competitor move;
3. a root-restricted search of Little Gambit's move, unless it is identical to the historical move.

The equal-node root-restricted score is the important quantity. Merely disagreeing with Stockfish's first PV move is not automatically an error: multiple root moves can be essentially equivalent.

## Metrics

For both the historical competitor and Little Gambit, CI reports mean/median centipawn loss, Stockfish WDL-expectation loss, best-move agreement and counts of >=30, >=80, >=150 and >=300 cp errors.

It also scores Little Gambit directly against the historical move. A candidate move more than 8 cp better is a pairwise win; within +/-8 cp is a tie; more than 8 cp worse is a loss. The small band avoids pretending tiny fixed-node score differences are exact.

A target gate passes only when Little Gambit has no illegal moves, is no worse in mean cp loss and WDL-expectation loss, scores at least 50% pairwise, does not produce more >=80 cp mistakes, and does not have more >=80 cp regressions than >=80 cp gains. The aggregate CI gate requires passing every target independently.

## What this benchmark does not prove

Passing is strong evidence that the candidate is choosing more Stockfish-accurate moves on this adversarial retained set. It does **not** by itself establish a higher Elo rating. Search speed, clock management, openings, repetition handling and error correlation across a continuous game still matter, so promotion should require both this gate and the existing real-clock / head-to-head qualification tests.

The corpus and all Stockfish-derived output are development-only. Do not package either into the competition agent.
