# Strength Laboratory

Status: **M5 foundation v1**

This document defines the offline diagnostic and teacher-data layer used to decide where the engine is
actually losing strength. It is deliberately outside the runtime dependency graph.

## 1. Governing rule

A chess idea is not promoted because it sounds correct. We need two complementary forms of evidence:

1. **match evidence** — paired equal-resource games decide whether a candidate improves the engine;
2. **diagnostic evidence** — full-strength teacher analysis identifies what kinds of positions and
   decisions are costing objective value.

The diagnostic layer does not replace matches. It improves the hypotheses we choose to spend matches
on.

## 2. Current production reference

At the creation of this document the production reference is:

```text
main@70484195439dc79d3610e36bcac88feb801a7721
benchmark: reference-search-v8
signature: 0x4c3bbe8701fbbb68
```

Its accepted search stack includes PVS, bounded qsearch, staged MovePicker, two killers, reverse
futility pruning, adaptive verified LMR v3, late-quiet futility and the RFP early legal-existence
probe.

The current `1+0.01` Stockfish-limited calibration is approximately 1830 on this project's protocol
scale. This is not a human/FIDE Elo claim.

## 3. Offline Python environment

The Rust engine has no Python runtime dependency. The analysis tools use a separate environment:

```sh
python3 -m venv .venv-analysis
. .venv-analysis/bin/activate
python -m pip install -r tools/requirements-analysis.txt
```

The pinned `chess` package is used for PGN parsing and UCI engine communication. It is an external
GPL-3.0+ analysis dependency and is not vendored or linked into engine binaries.

## 4. Full-strength Stockfish mistake mining

Use full-strength Stockfish for diagnosis. Do **not** use `UCI_LimitStrength` for teacher analysis.

Example:

```sh
python3 scripts/stockfish_error_mining.py \
  --pgn results/games.pgn \
  --engine-name 'Chess-Rust@7048419' \
  --stockfish /absolute/path/to/stockfish \
  --nodes 100000 \
  --threads 1 \
  --hash-mb 32 \
  --output-dir results/error-mine-100k
```

For every move played by the selected engine the miner performs two equal fixed-node searches:

```text
unrestricted teacher search
vs
teacher search restricted to the move actually played
```

The output contains:

- FEN before the move;
- played SAN/UCI move;
- Stockfish preferred move;
- played/best centipawn-like teacher scores;
- played/best WDL expectation;
- objective score and expectation loss;
- phase;
- played/best move class;
- forcing/non-forcing labels;
- teacher depth, seldepth, nodes, NPS and PV;
- clock value when the PGN contains `%clk` data.

The output directory is immutable evidence and contains:

```text
manifest.json
positions.jsonl
positions.csv
summary.json
```

`manifest.json` hashes the input PGN and Stockfish binary and records teacher identity, node budget,
threads, hash and Python analysis-package version.

## 5. How to use the error data

The first pass should rank positions by WDL expectation loss and centipawn loss, then inspect clusters
rather than isolated anecdotes.

Useful slices include:

- quiet move played, forcing best move;
- quiet move played, quiet best move;
- capture played, quiet best move;
- large losses by opening/middlegame/endgame phase;
- repeated exchange mistakes;
- king-safety failures;
- passed-pawn/endgame conversion failures;
- positions with adequate clock but poor move quality;
- errors concentrated late in the game or under clock pressure.

The automated labels are deliberately coarse. A `quiet` classification is a factual move property,
not proof that an error is "positional". Human/engine inspection of the largest clusters remains
necessary before choosing a mechanism.

## 6. Learned-evaluation teacher data

Generate teacher positions with:

```sh
python3 scripts/generate_nnue_teacher_data.py \
  --stockfish /absolute/path/to/stockfish \
  --pgn selfplay-a.pgn \
  --pgn selfplay-b.pgn \
  --epd match/openings/m3-uho-lichess-100-v1.epd \
  --nodes 100000 \
  --stride 2 \
  --output-dir data/nnue-teacher-v1
```

Every record contains:

- canonical FEN;
- side to move;
- fixed-budget teacher CP/mate score;
- teacher WDL expectation and W/D/L counts;
- best move and PV;
- teacher depth/nodes/NPS;
- source group and source position;
- deterministic train/validation/holdout assignment.

### Leakage rule

PGN positions are split by **whole game**, never by individual position. Adjacent positions from one
game therefore cannot appear in both training and validation/holdout sets.

EPD positions use one source line as the grouping unit. If a future source contains families of related
EPDs, preprocess them into stronger shared groups before training.

## 7. Dataset provenance

A dataset is not identified merely by its row count. Retain:

```text
source file hashes
teacher executable hash + UCI identity
teacher nodes/threads/hash
selection stride/range
split salt and percentages
generator revision
output hash
```

Never silently append positions generated under a different teacher budget to an existing dataset.
Create a new dataset identity.

## 8. Diagnostic cadence

Run mistake mining at meaningful production milestones, not after every tiny search patch.

Recommended points:

1. current classical production;
2. after major semantics-neutral throughput gains settle;
3. first accepted learned evaluator;
4. after major search retuning around the learned evaluator;
5. each external-calibration milestone (~2000, ~2200, ~2400, ...).

This allows us to ask whether an old weakness actually disappeared rather than assuming a mechanism
fixed it.

## 9. Relationship to match qualification

Teacher analysis is allowed to use a large deterministic fixed-node budget because it is offline.
Candidate-vs-reference strength qualification remains equal-resource Fastchess play under the frozen
match protocol.

A feature may look excellent in teacher diagnostics and still lose Elo because it costs too much. The
final acceptance metric remains equal-time match strength.
