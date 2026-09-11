# AI Chessathon top-engine move benchmark

This directory freezes the deduplicated offline corpus built from the two retained Chessathon archives supplied on 2026-09-11.

- downloaded PGNs: **114**
- unique semantic games: **71**
- duplicate copies removed: **43**
- deduplicated PGN SHA-256: `81c44dee067b39db09938f159e3192245abc5c4c52896b986b71f53b1cce5187`
- initial top panel: the eight engines appearing in at least ten unique games
- historical decisions by the panel before position/FEN deduplication: **8,230**

The corpus is stored as gzip data encoded into `chunk_*.b64`. Reconstruct it with:

```bash
cat match/benchmarks/aichessathon-top-engines/chunk_*.b64 \
  | base64 -d \
  | gzip -d \
  > /tmp/aichessathon-top-engine-corpus.pgn
sha256sum /tmp/aichessathon-top-engine-corpus.pgn
```

The standard screen samples 48 candidate-blind, phase-balanced positions per target and evaluates the historical move and Little Gambit's move with full-strength Stockfish at equal fixed-node root budgets. The aggregate gate requires Little Gambit to have lower Stockfish centipawn loss and a strict pairwise majority against **every** target, while not increasing large-error counts.

The benchmark is an **offline research artifact only**. Competition submissions must not contain the historical moves, Stockfish labels, or a lookup table derived from them. Opening books and permitted trained models remain separate from this benchmark.

## Standard screen

```bash
CORPUS=/tmp/aichessathon-top-engine-corpus.pgn
ENGINE=/path/to/unpacked/candidate
SF=/path/to/stockfish
OUT=/tmp/top-engine-benchmark
mkdir -p "$OUT"

while IFS= read -r target; do
  slug=$(printf '%s' "$target" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9_-')
  python scripts/v18_competitor_move_benchmark.py \
    --pgn "$CORPUS" \
    --engine-dir "$ENGINE" \
    --stockfish "$SF" \
    --target "$target" \
    --positions 48 \
    --nodes 200000 \
    --threads 1 \
    --hash-mb 64 \
    --output-dir "$OUT/$slug"
done < match/benchmarks/aichessathon-top-engines/targets.txt

python scripts/v18_competitor_benchmark_gate.py "$OUT"/*/summary.json \
  --output "$OUT/gate.json"
```

For final certification, rerun with all available unique target positions and a larger Stockfish node budget, then confirm any promoted engine with paired real-clock games. The static benchmark is a high-signal development gate, not an Elo estimate.