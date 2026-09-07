# M6-A Bullet NNUE trainer

This directory is a **standalone training workspace**. It is intentionally not a member of the engine's root Cargo workspace, so CUDA/ROCm/Metal and Bullet never enter normal engine, CI, native, or WASM dependency graphs.

## Frozen trainer identity

- Bullet repository: `https://github.com/jw1912/bullet`
- pinned commit: `629ee50000b2afb7b3337595401c830d3b1e0f42`
- first architecture: `(768 -> 512) x 2 -> 1`
- inputs: dual-perspective `Chess768`
- activation: SCReLU
- eval scale: `400`
- quantisation: `QA=255`, `QB=64`
- score/WDL mix: `75%` WDL target

The first M6 generation deliberately uses the basic 768 piece-square feature set. Bullet's own progression guide warns that HalfKA/HalfKP-scale input spaces often need much more data and training effort before they beat simpler inputs. We will only add king buckets, threats, pawn pairs, output buckets, or extra layers after a simpler network has won at equal nodes and equal time.

## Data

For serious training, prefer a binpack-like format. The trainer supports:

- `viri` — Viriformat binpack using Bullet's default filter;
- `sf` / `stockfish` — Stockfish binpack with a conservative quiet/non-check training filter;
- `bullet` — direct BulletFormat data for smoke tests and small experiments.

The M6 data programme is intentionally staged:

1. **pilot**: 100M–500M broad positions;
2. **generation B**: 1B+ positions if M6-A wins;
3. mix in a minority of certified Rust search-leaf and targeted-error positions;
4. only then increase feature complexity/capacity.

Search-leaf corpora are distribution anchors, not the primary chess-knowledge source.

## Build / train

NVIDIA/CUDA:

```bash
cargo run --release --features cuda -- \
  viri /path/to/data.vf /path/to/checkpoints
```

The optional final positional arguments are `superbatches` and `batches-per-superbatch`:

```bash
cargo run --release --features cuda -- \
  viri /path/to/data.vf /path/to/checkpoints 8 1526
```

Defaults are 8 superbatches × 1,526 batches × 16,384 positions, roughly 200M training samples. Repeated positions/epochs depend on corpus size.

Loader controls:

```bash
CHESS_NNUE_LOADER_THREADS=4 CHESS_NNUE_BUFFER_MB=1024 \
  cargo run --release --features cuda -- viri data.vf checkpoints
```

ROCm and Metal can be selected with `--features rocm` or `--features metal` on supported systems.

## Promotion gates

A checkpoint is **not** promoted because its training loss or centipawn RMSE improves.

The required sequence is:

1. retained data + trainer + checkpoint provenance;
2. quantised runtime oracle agrees with Bullet output on a frozen FEN fixture;
3. equal-node paired strength test vs current production;
4. incremental accumulator implementation and cost benchmark;
5. equal-time SPRT/qualification;
6. only then consider a production merge and retune pruning/history around it.

This keeps model quality and runtime cost causally separate.
