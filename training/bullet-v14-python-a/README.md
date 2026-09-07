# Python V14-A compact NNUE student trainer

This is a standalone Bullet workspace for the Python/Numba V14 evaluator lane. It deliberately shares the M6-A data semantics and quantisation contract while varying only hidden width.

## Frozen common contract

- Bullet commit: `629ee50000b2afb7b3337595401c830d3b1e0f42`
- inputs: dual-perspective `Chess768`
- activation: SCReLU
- eval scale: `400`
- quantisation: `QA=255`, `QB=64`
- score/WDL mix: `75%` WDL target
- batch size: `16,384`

The first ladder is restricted to **64 / 96 / 128 / 192** hidden units. No other architectural variable changes in this experiment.

The purpose is not to imitate the Rust 512-wide deployment network. The purpose is to find the best **equal-time strength per CPU cost** point for Numba while training on the same broad corpus and target semantics.

## Usage

```bash
cargo run --release --features cuda -- \
  viri /path/to/data.vf /path/to/checkpoints 128
```

Optional final arguments are superbatches and batches per superbatch:

```bash
cargo run --release --features cuda -- \
  viri data.vf checkpoints 128 8 1526
```

The same `viri`, `sf`/`stockfish`, and `bullet` loaders as M6-A are supported.

## Promotion gates

A width is not selected from training loss alone. Each checkpoint must pass:

1. exact trainer/data/checkpoint provenance;
2. quantised inference oracle on frozen FENs;
3. equal-node comparison against V13 classical + 1/6 residual;
4. measured incremental-update cost in the exact Python/Numba runtime;
5. equal-time paired games at the competition control;
6. fresh-book replication / SPRT before any V14 integration.

Only after a width survives those gates do we consider blending/replacing the V13 evaluator or retuning search around it.

The trainer API itself is CI-gated before any expensive GPU run; GPU checkpoints remain external, immutable experiment artifacts rather than repository state.
