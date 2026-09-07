#!/usr/bin/env python3
"""Train a deterministic NNUE correction on top of the accepted classical evaluator.

The input JSONL uses the same schema as the absolute teacher corpus, but `teacher_cp` is the desired
residual `Stockfish target - classical evaluation`. The exported `CHNNUE1` network therefore predicts
only a correction. Zero-output initialization makes epoch zero exactly equivalent to trusting the
classical evaluator, and the selected checkpoint is chosen from validation loss only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from array import array
from pathlib import Path

from train_nnue_reference import (
    FEATURE_SET_ID,
    HEADER_LEN,
    SUPPORTED_HIDDEN,
    ReferenceNetwork,
    build_network_blob,
    canonical_json_bytes,
    fnv1a64,
    load_examples,
    sha256_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--teacher-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--hidden", type=int, choices=SUPPORTED_HIDDEN, default=32)
    parser.add_argument("--epochs", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=0.0001)
    parser.add_argument("--seed", type=int, default=20260907)
    parser.add_argument("--target-clip-cp", type=float, default=2000.0)
    return parser.parse_args()


def snapshot(model: ReferenceNetwork) -> tuple[array, array, array, float]:
    return (
        array("f", model.input_bias),
        array("f", model.input_weights),
        array("f", model.output_weights),
        model.output_bias,
    )


def restore(model: ReferenceNetwork, state: tuple[array, array, array, float]) -> None:
    model.input_bias, model.input_weights, model.output_weights, model.output_bias = state


def main() -> int:
    args = parse_args()
    if args.epochs <= 0:
        raise SystemExit("--epochs must be positive")
    if args.learning_rate <= 0:
        raise SystemExit("--learning-rate must be positive")
    if not args.teacher_id.strip():
        raise SystemExit("--teacher-id must be non-empty")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    examples = load_examples(
        args.teacher,
        target_clip_cp=args.target_clip_cp,
        max_records=None,
    )
    train = [example for example in examples if example.split == "train"]
    validation = [example for example in examples if example.split == "validation"]
    holdout = [example for example in examples if example.split == "holdout"]
    if not train or not validation or not holdout:
        raise ValueError("residual training requires non-empty train, validation and holdout splits")

    model = ReferenceNetwork(args.hidden, args.seed)
    # The safety prior is the accepted evaluator: before training, predicted correction is exactly 0.
    model.output_weights = array("f", [0.0] * (args.hidden * 2))
    model.output_bias = 0.0

    initial_validation_mse = model.mse(validation)
    assert initial_validation_mse is not None
    best_validation_mse = initial_validation_mse
    best_epoch = 0
    best_state = snapshot(model)
    epoch_train_mse: list[float] = []
    epoch_validation_mse: list[float] = []
    order = list(range(len(train)))
    rng = random.Random(args.seed ^ 0x52455349)

    for epoch in range(1, args.epochs + 1):
        rng.shuffle(order)
        total = 0.0
        for index in order:
            total += model.train_one(train[index], args.learning_rate)
        train_mse = total / len(train)
        validation_mse = model.mse(validation)
        assert validation_mse is not None
        epoch_train_mse.append(train_mse)
        epoch_validation_mse.append(validation_mse)
        if validation_mse < best_validation_mse:
            best_validation_mse = validation_mse
            best_epoch = epoch
            best_state = snapshot(model)

    restore(model, best_state)
    selected_holdout_mse = model.mse(holdout)
    assert selected_holdout_mse is not None

    teacher_sha256 = sha256_file(args.teacher)
    training_metadata = {
        "schema_version": 1,
        "trainer": "scripts/train_nnue_residual_reference.py",
        "target_mode": "stockfish_minus_classical",
        "feature_set_id": FEATURE_SET_ID,
        "teacher_id": args.teacher_id,
        "teacher_sha256": teacher_sha256,
        "hidden": args.hidden,
        "epochs_available": args.epochs,
        "selected_epoch": best_epoch,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "target_clip_cp": args.target_clip_cp,
        "records_loaded": len(examples),
        "train_records": len(train),
        "validation_records": len(validation),
        "holdout_records": len(holdout),
        "initial_zero_residual_validation_mse": initial_validation_mse,
        "epoch_train_mse": epoch_train_mse,
        "epoch_validation_mse": epoch_validation_mse,
        "selected_validation_mse": best_validation_mse,
        "selected_holdout_mse": selected_holdout_mse,
        "selection_rule": "minimum validation MSE including zero-residual epoch 0",
        "initialization": "random sparse input transform; exact zero output correction",
    }
    metadata_bytes = canonical_json_bytes(training_metadata)
    metadata_hash = hashlib.sha256(metadata_bytes).digest()
    (args.output_dir / "training-metadata.json").write_bytes(metadata_bytes)

    blob = build_network_blob(model, metadata_hash)
    network_path = args.output_dir / f"nnue-residual-{args.hidden}-v1.nnue"
    network_path.write_bytes(blob)
    export_manifest = {
        "schema_version": 1,
        "network": network_path.name,
        "network_sha256": hashlib.sha256(blob).hexdigest(),
        "network_bytes": len(blob),
        "training_metadata": "training-metadata.json",
        "training_metadata_sha256": metadata_hash.hex(),
        "payload_checksum_fnv1a64": f"0x{fnv1a64(blob[HEADER_LEN:]):016x}",
        "selected_epoch": best_epoch,
        "selected_validation_mse": best_validation_mse,
    }
    (args.output_dir / "export-manifest.json").write_bytes(canonical_json_bytes(export_manifest))
    print(json.dumps(export_manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
