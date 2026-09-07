# M6 training data

Large training corpora are **not committed to this repository**. This directory contains small immutable manifests describing exactly what a training run consumed.

Every external corpus manifest must pin:

- provider/repository;
- immutable revision;
- exact filename;
- byte length;
- SHA-256 of the file contents;
- format;
- source licence;
- intended role and distribution policy.

The fetcher verifies all of those before training:

```bash
python -m pip install huggingface_hub
python scripts/fetch_m6_training_data.py \
  --manifest training/data/m6-pilot-pylon.json \
  --output /data/chess/training_data_pylon.binpack \
  --acknowledge-license ODbL-1.0 \
  --lock /data/chess/m6-pilot-pylon.lock.json
```

To validate an existing copy without network access:

```bash
python scripts/fetch_m6_training_data.py \
  --manifest training/data/m6-pilot-pylon.json \
  --verify-only /data/chess/training_data_pylon.binpack \
  --lock /data/chess/m6-pilot-pylon.lock.json
```

The lock file records both the manifest hash and verified content hash. It is an experiment artifact; the absolute local path is deliberately **not** part of model identity.

## M6 pilot corpus

`m6-pilot-pylon.json` pins Stockfish's `training_data_pylon.binpack` at the immutable Hugging Face dataset commit where it was introduced. The upstream collection is marked **ODbL**. We therefore classify this corpus as `research-pilot-only` until the licensing consequences for redistribution of derived weights have been reviewed explicitly.

This distinction is intentional:

- the pilot answers whether a properly trained modern evaluator has the expected Elo ceiling;
- a production-shipped network may later be retrained from our own generated corpus or another source with a clearly suitable redistribution path;
- no external dataset licence is silently converted into an assumption about our final model licence.

## First training command

Once the corpus has been verified:

```bash
cd training/bullet-m6-a
cargo run --release --features cuda -- \
  sf /data/chess/training_data_pylon.binpack /data/chess/checkpoints/m6-a
```

The default schedule processes about 200 million training samples. Equal-node chess strength—not training loss—is the promotion gate.
