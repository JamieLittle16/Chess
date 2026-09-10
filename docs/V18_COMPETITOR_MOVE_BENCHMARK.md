# V18 Chessathon Top-Engine Move Benchmark

Status: **new offline strength gate**

This benchmark asks a deliberately narrow competitive question:

> On positions in which the strongest repeatedly observed Chessathon opponents actually had to move,
> does the current Little Gambit candidate choose moves that full-strength Stockfish judges to be at
> least as accurate, and ultimately more accurate, than the historical opponent move?

It is a diagnostic and regression benchmark. It is **not** a substitute for paired games or Elo.

## Corpus

The 2026-09-11 corpus was formed from two user-retained Chessathon PGN downloads. There were 114 PGN
entries but only 71 unique games after semantic deduplication. Forty-three duplicate copies were
removed. Game identity ignores filename/download-copy noise and is based on starting FEN plus
normalized mainline moves.

The initial top-engine panel is the set of opponents with at least 10 appearances in those 71 unique
games:

- Ryan Vincent — 17 games
- Lightning Tree — 14
- Emile Andrieu — 13
- what even is en passant — 13
- Gijs Smit — 12
- Opus Carlsen — 12
- Stonkfish — 11
- BetaGo — 10

The exact source hashes and appearance counts are frozen in
`match/benchmarks/aichessathon-top-engines/manifest.json`.

The deduplicated PGN is intentionally treated as an **offline research artifact**, not submission
payload. Competition rules prohibit shipping a table of engine moves/evaluations for runtime lookup.
Opening books and permitted endgame tablebases are a separate matter.

## Position selection

For a target engine, `scripts/v18_competitor_move_benchmark.py` reconstructs every position immediately
before that engine moved.

Repeated occurrences of the same FEN for the same target are collapsed because the competition agent
sees only FEN and clock, not the historical PGN identity. The latest corpus occurrence is retained.

The default screen selects at most 48 positions per target and deliberately balances the engine's
24-point phase convention across:

- opening / early middlegame;
- middlegame;
- endgame.

Selection uses a fixed SHA-256 ordering from seed `20260911`; it does not depend on the candidate's
moves or Stockfish scores. This prevents cherry-picking favourable positions after seeing results.

The candidate receives the exact FEN and the best available reconstruction of its pre-move clock. The
first move for a side starts from the Chessathon 120-second base; later moves use the previous `%clk`
comment for that side. The competition increment is already reflected by retained post-move clocks.

Every static probe starts with cleared game/search state so one benchmark position cannot donate TT or
history information to another.

## Stockfish teacher protocol

Use current stable full-strength Stockfish, one thread, explicit hash, and a fixed node count. Do not
use `UCI_LimitStrength` for this benchmark.

For each selected FEN, Stockfish receives equal-budget searches for:

1. unrestricted best play;
2. the historical opponent root move;
3. Little Gambit's candidate root move.

If Little Gambit chose the historical move, the restricted analysis is reused rather than searched a
second time.

This yields both centipawn-like loss and Stockfish WDL-expectation loss. Root-restricted scoring is
important: best-move agreement alone incorrectly treats two near-equivalent moves as qualitatively
different and tells us nothing about how costly a disagreement is.

Default teacher budget: **200,000 nodes per root analysis**. For certification, raise the node budget
and/or remove the 48-position cap.

Stockfish 19 is the preferred teacher for this corpus. Pin the actual executable hash in each result;
never rely on a version name alone.

## Pairwise score

For each position:

```text
candidate_delta = Stockfish(candidate move) - Stockfish(historical move)
```

from the mover's point of view.

With the default 8 cp noise/equivalence band:

- delta > +8 cp: candidate win, 1 point;
- -8 cp <= delta <= +8 cp: tie, 0.5 points;
- delta < -8 cp: candidate loss, 0 points.

This is intentionally stricter and more informative than asking whether Little Gambit copied
Stockfish's PV move.

## Gates

There are two levels.

### Regression gate

A candidate is not allowed to move backwards. Per target it must have:

- zero illegal moves;
- mean cp loss no worse than the historical engine;
- mean WDL-expectation loss no worse;
- pairwise score at least 50%;
- no increase in >=80 cp mistakes;
- no more >=80 cp regressions than >=80 cp gains.

This is the `gate_pass` field written by the per-engine runner.

### Outperformance gate

The project goal is stronger than merely tying the field. The multi-engine gate in
`scripts/v18_competitor_benchmark_gate.py` requires **every target engine** to pass the regression gate
and, by default:

- Little Gambit mean cp loss at least 0.5 cp lower on that target's selected positions;
- pairwise score strictly above 50%;
- Stockfish-best-move match rate no worse;
- >=80 cp mistake count no worse.

Only when **all eight** targets pass do we call the benchmark an outperformance pass.

The 0.5 cp strict margin is deliberately small because fixed-node teacher noise exists; convincing
claims should be rerun at a larger teacher budget and should survive paired games.

## Recommended ladder

Use three progressively more expensive screens:

1. **Smoke:** 16 positions/engine, 50k-100k Stockfish nodes. Fast rejection only.
2. **Standard:** 48 phase-balanced positions/engine, 200k nodes. Development gate.
3. **Certification:** all unique positions for every panel engine, 500k+ nodes, followed by paired
   real-clock games. This is the evidence used before claiming the engine is genuinely stronger.

Do not tune against a single dramatic position. The value of this suite is the distribution across
real decisions made by strong opponents.

## Example

```sh
python scripts/v18_competitor_move_benchmark.py \
  --pgn /path/to/aichessathon-top-engine-corpus-deduped.pgn \
  --engine-dir /path/to/unpacked/punch133 \
  --stockfish /path/to/stockfish \
  --target 'Lightning Tree' \
  --positions 48 \
  --nodes 200000 \
  --threads 1 \
  --hash-mb 64 \
  --output-dir results/top-engine/lightning-tree
```

Run the same command for every panel target, then aggregate the eight `summary.json` files:

```sh
python scripts/v18_competitor_benchmark_gate.py \
  results/top-engine/*/summary.json \
  --output results/top-engine/gate.json
```

A static accuracy pass means we have earned the right to run the expensive match confirmation. It does
not by itself guarantee a higher Chessathon score: time management, game-state history, openings,
search instability and correlated positions can still change actual match strength.
