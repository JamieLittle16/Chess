# V14 serious NNUE data plan

The 1,827-position H64/H96 corpus is a pilot used to validate architecture, incremental runtime,
quantisation and whether a learned correction contains any transferable signal.  It is **not** the
final V14 training corpus.

## Why not copy one Stockfish dataset verbatim?

The current Stockfish training ecosystem is designed around very large binpack corpora, supports
multiple interleaved data files, WDL-aware objectives, and game-testing of generated checkpoints.
There is not one immutable small public corpus that should simply be copied into Little Gambit.
Moreover, a Python competition engine has a different search distribution and a much tighter
inference-cost budget than Stockfish.

## V14 target mixture

Use a multi-source corpus with source identity retained on every record.  The initial engineering
mixture target is:

- **50-60% broad strong-engine/search-leaf positions**: many opening families, tactical and quiet
  middlegames, imbalanced structures and varied evaluations;
- **20-30% Little-Gambit search distribution**: V13/V14 static-eval/search-leaf positions generated
  at multiple fixed-node budgets and from diverse opening roots;
- **10-15% hard diagnostic positions**: high teacher-loss positions with emphasis on king safety,
  rook penetration, prophylaxis, tactical capture exactness and attack-to-consolidation transitions;
- **5-10% endgame-rich data**: rook/pawn endings, minor-piece endings, king/pawn races, promotion
  races and tablebase-resolvable material where practical.

These percentages are V14 engineering priors, not claimed Stockfish proportions.  They should be
changed only from held-out/game evidence rather than validation-loss fishing.

## Scale

A serious generation should start in the **hundreds of thousands to low millions** of deduplicated
positions, not thousands.  If the H64/H96 family survives equal-node/equal-time games, scale further.
The repository already has a certified 28,301-position Rust search-leaf corpus that can contribute one
source family after relabelling; it must not dominate the Python-specific distribution.

## Labels / objective

Retain for each position:

- fixed-provenance Stockfish score;
- WDL expectation/result information when available;
- teacher best move / PV metadata for diagnostics;
- source/game/root id;
- phase/material/context metadata used only for analysis and stratified reporting.

Prefer a WDL/search-aligned training objective or predetermined CP/WDL mixture over pure CP MSE.
Previous repository experiments proved that large CP/MSE improvements can still reduce playing
strength badly.

## Leakage discipline

- deduplicate positions globally;
- split by whole game/root/source group, never adjacent positions;
- keep at least one complete source family untouched as an external holdout;
- do not use rated-game regression fixtures for ordinary hyperparameter selection;
- keep final checkpoint selection game-gated at equal nodes and equal time.

## Promotion gates

No network enters the V14 stack from offline loss alone.  Required evidence remains:

1. incremental == full rebuild;
2. quantised == reference inference within pinned tolerance;
3. measured real-search NPS/inference cost;
4. broad regression/teacher-loss screen;
5. paired equal-node games on unseen opening/source groups;
6. fresh replication;
7. equal-time games;
8. only then search-constant retuning on top of the accepted evaluator.
