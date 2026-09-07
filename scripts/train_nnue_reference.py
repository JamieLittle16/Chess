#!/usr/bin/env python3
"""Train and export the first deterministic king-piece-v1 NNUE reference model.

This trainer is intentionally dependency-light and correctness-oriented. It uses only the pinned
python-chess analysis dependency plus Python's standard library, implements sparse SGD directly, and
exports the exact `CHNNUE1` integer format consumed by `chess-eval`. It is not intended to be the
final high-throughput GPU trainer; its job is to freeze target semantics, feature identity,
quantization and artifact provenance before a faster trainer is introduced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import struct
from array import array
from pathlib import Path
from typing import Iterable, NamedTuple

import chess

FEATURE_SET_ID = "king-piece-v1"
FEATURE_COUNT = 24_576
SUPPORTED_HIDDEN = (32, 64, 128)
ACTIVATION_FLOAT_MAX = 1.0
INPUT_QUANT = 127
OUTPUT_QUANT = 64
ACTIVATION_QUANT_MAX = 127
OUTPUT_SCALE = INPUT_QUANT * OUTPUT_QUANT
MAX_ABS_QUANT_WEIGHT = 4096
MAGIC = b"CHNNUE1\0"
FORMAT_VERSION = 1
HEADER_LEN = 98
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3


class Example(NamedTuple):
    white: tuple[int, ...]
    black: tuple[int, ...]
    side_to_move: bool
    target_cp: float
    split: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument(
        "--teacher-id",
        default=None,
        help=(
            "stable logical corpus identity stored in model provenance; defaults to the teacher "
            "file SHA-256 and never uses an absolute filesystem path"
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--hidden", type=int, choices=SUPPORTED_HIDDEN, default=32)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=0.0005)
    parser.add_argument("--seed", type=int, default=20260907)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--target-clip-cp", type=float, default=2000.0)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def active_features(board: chess.Board, perspective: bool) -> tuple[int, ...]:
    king = board.king(perspective)
    if king is None:
        raise ValueError("position is missing perspective king")

    king_file = chess.square_file(king)
    king_rank = chess.square_rank(king)
    relative_king_rank = king_rank if perspective == chess.WHITE else 7 - king_rank
    mirror_files = king_file >= 4
    canonical_king_file = 7 - king_file if mirror_files else king_file
    bucket = relative_king_rank * 4 + canonical_king_file

    features: list[int] = []
    for square, piece in board.piece_map().items():
        ownership = 0 if piece.color == perspective else 1
        plane = ownership * 6 + (piece.piece_type - 1)
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        relative_rank = rank if perspective == chess.WHITE else 7 - rank
        if mirror_files:
            file = 7 - file
        oriented_square = relative_rank * 8 + file
        feature = bucket * 12 * 64 + plane * 64 + oriented_square
        if not 0 <= feature < FEATURE_COUNT:
            raise AssertionError("feature index escaped king-piece-v1 range")
        features.append(feature)
    features.sort()
    return tuple(features)


def load_examples(path: Path, *, target_clip_cp: float, max_records: int | None) -> list[Example]:
    examples: list[Example] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            cp = record.get("teacher_cp")
            if cp is None:
                continue
            board = chess.Board(record["fen"])
            target = max(-target_clip_cp, min(target_clip_cp, float(cp)))
            examples.append(
                Example(
                    white=active_features(board, chess.WHITE),
                    black=active_features(board, chess.BLACK),
                    side_to_move=board.turn,
                    target_cp=target,
                    split=str(record.get("split", "train")),
                )
            )
            if max_records is not None and len(examples) >= max_records:
                break
    if not examples:
        raise ValueError(f"{path}: no usable non-mate teacher_cp records")
    return examples


class ReferenceNetwork:
    def __init__(self, hidden: int, seed: int) -> None:
        self.hidden = hidden
        rng = random.Random(seed)
        self.input_bias = array("f", [0.01] * hidden)
        self.input_weights = array(
            "f", (rng.uniform(-0.01, 0.01) for _ in range(FEATURE_COUNT * hidden))
        )
        self.output_weights = array("f", (rng.uniform(-0.02, 0.02) for _ in range(hidden * 2)))
        self.output_bias = 0.0

    def accum(self, features: Iterable[int]) -> list[float]:
        values = list(self.input_bias)
        hidden = self.hidden
        weights = self.input_weights
        for feature in features:
            base = feature * hidden
            for neuron in range(hidden):
                values[neuron] += weights[base + neuron]
        return values

    @staticmethod
    def activate(value: float) -> float:
        return max(0.0, min(ACTIVATION_FLOAT_MAX, value))

    def forward(
        self, example: Example
    ) -> tuple[float, list[float], list[float], list[float], list[float]]:
        white_acc = self.accum(example.white)
        black_acc = self.accum(example.black)
        if example.side_to_move == chess.WHITE:
            us_acc, them_acc = white_acc, black_acc
        else:
            us_acc, them_acc = black_acc, white_acc
        us_act = [self.activate(value) for value in us_acc]
        them_act = [self.activate(value) for value in them_acc]
        value = self.output_bias
        for neuron in range(self.hidden):
            value += us_act[neuron] * self.output_weights[neuron]
            value += them_act[neuron] * self.output_weights[self.hidden + neuron]
        return value, white_acc, black_acc, us_act, them_act

    def train_one(self, example: Example, learning_rate: float) -> float:
        prediction, white_acc, black_acc, us_act, them_act = self.forward(example)
        error = prediction - example.target_cp
        # Huber-style derivative keeps one extreme teacher score from destabilising the reference
        # trainer while preserving ordinary MSE behaviour near the target.
        grad = max(-200.0, min(200.0, error))

        old_output = list(self.output_weights)
        for neuron in range(self.hidden):
            self.output_weights[neuron] -= learning_rate * grad * us_act[neuron]
            self.output_weights[self.hidden + neuron] -= learning_rate * grad * them_act[neuron]
        self.output_bias -= learning_rate * grad

        white_grad = [0.0] * self.hidden
        black_grad = [0.0] * self.hidden
        if example.side_to_move == chess.WHITE:
            us_grad, them_grad = white_grad, black_grad
            us_pre, them_pre = white_acc, black_acc
        else:
            us_grad, them_grad = black_grad, white_grad
            us_pre, them_pre = black_acc, white_acc

        for neuron in range(self.hidden):
            if 0.0 < us_pre[neuron] < ACTIVATION_FLOAT_MAX:
                us_grad[neuron] = grad * old_output[neuron]
            if 0.0 < them_pre[neuron] < ACTIVATION_FLOAT_MAX:
                them_grad[neuron] = grad * old_output[self.hidden + neuron]

        # Input weights are shared by both perspective accumulators. Sum their gradients before the
        # update when the same canonical feature is active in both frames.
        feature_grads: dict[int, list[float]] = {}
        for features, perspective_grad in ((example.white, white_grad), (example.black, black_grad)):
            for feature in features:
                slots = feature_grads.setdefault(feature, [0.0] * self.hidden)
                for neuron in range(self.hidden):
                    slots[neuron] += perspective_grad[neuron]

        for neuron in range(self.hidden):
            self.input_bias[neuron] -= learning_rate * (white_grad[neuron] + black_grad[neuron])
        for feature, gradients in feature_grads.items():
            base = feature * self.hidden
            for neuron, feature_grad in enumerate(gradients):
                self.input_weights[base + neuron] -= learning_rate * feature_grad

        return error * error

    def mse(self, examples: Iterable[Example]) -> float | None:
        total = 0.0
        count = 0
        for example in examples:
            prediction = self.forward(example)[0]
            error = prediction - example.target_cp
            total += error * error
            count += 1
        return total / count if count else None


def quantize_i16(value: float, scale: int) -> int:
    quantized = int(round(value * scale))
    return max(-MAX_ABS_QUANT_WEIGHT, min(MAX_ABS_QUANT_WEIGHT, quantized))


def fnv1a64(payload: bytes) -> int:
    value = FNV_OFFSET
    for byte in payload:
        value ^= byte
        value = (value * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def build_payload(network: ReferenceNetwork) -> bytes:
    payload = bytearray()
    for value in network.input_bias:
        payload += struct.pack("<h", quantize_i16(value, INPUT_QUANT))
    for value in network.input_weights:
        payload += struct.pack("<h", quantize_i16(value, INPUT_QUANT))
    for value in network.output_weights:
        payload += struct.pack("<h", quantize_i16(value, OUTPUT_QUANT))
    output_bias = int(round(network.output_bias * OUTPUT_SCALE))
    output_bias = max(-(2**31), min(2**31 - 1, output_bias))
    payload += struct.pack("<i", output_bias)
    return bytes(payload)


def build_network_blob(network: ReferenceNetwork, training_metadata_sha256: bytes) -> bytes:
    payload = build_payload(network)
    feature_id = FEATURE_SET_ID.encode()
    if len(feature_id) > 32:
        raise ValueError("feature id exceeds CHNNUE1 header field")
    feature_field = feature_id + bytes(32 - len(feature_id))
    header = b"".join(
        [
            MAGIC,
            struct.pack("<H", FORMAT_VERSION),
            feature_field,
            struct.pack("<I", FEATURE_COUNT),
            struct.pack("<H", network.hidden),
            struct.pack("<h", ACTIVATION_QUANT_MAX),
            struct.pack("<i", OUTPUT_SCALE),
            struct.pack("<I", len(payload)),
            struct.pack("<Q", fnv1a64(payload)),
            training_metadata_sha256,
        ]
    )
    if len(header) != HEADER_LEN:
        raise AssertionError(f"CHNNUE1 header length {len(header)} != {HEADER_LEN}")
    return header + payload


def main() -> int:
    args = parse_args()
    if args.epochs <= 0:
        raise SystemExit("--epochs must be positive")
    if args.learning_rate <= 0:
        raise SystemExit("--learning-rate must be positive")
    if args.teacher_id is not None and not args.teacher_id.strip():
        raise SystemExit("--teacher-id must be non-empty when supplied")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    teacher_sha256 = sha256_file(args.teacher)
    teacher_id = args.teacher_id or f"sha256:{teacher_sha256}"
    examples = load_examples(
        args.teacher,
        target_clip_cp=args.target_clip_cp,
        max_records=args.max_records,
    )
    train = [example for example in examples if example.split == "train"]
    validation = [example for example in examples if example.split == "validation"]
    holdout = [example for example in examples if example.split == "holdout"]
    if not train:
        # Small smoke/reference corpora may omit an explicit split. Treat every record as training
        # only when there are genuinely no `train` records.
        train = list(examples)

    model = ReferenceNetwork(args.hidden, args.seed)
    epoch_losses: list[float] = []
    order = list(range(len(train)))
    rng = random.Random(args.seed ^ 0x4E4E5545)
    for _epoch in range(args.epochs):
        rng.shuffle(order)
        total = 0.0
        for index in order:
            total += model.train_one(train[index], args.learning_rate)
        epoch_losses.append(total / len(train))

    training_metadata = {
        "schema_version": 1,
        "trainer": "scripts/train_nnue_reference.py",
        "feature_set_id": FEATURE_SET_ID,
        "teacher_id": teacher_id,
        "teacher_sha256": teacher_sha256,
        "hidden": args.hidden,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "target_clip_cp": args.target_clip_cp,
        "records_loaded": len(examples),
        "train_records": len(train),
        "validation_records": len(validation),
        "holdout_records": len(holdout),
        "epoch_train_mse": epoch_losses,
        "final_validation_mse": model.mse(validation),
        "final_holdout_mse": model.mse(holdout),
        "quantization": {
            "input_scale": INPUT_QUANT,
            "output_weight_scale": OUTPUT_QUANT,
            "activation_max": ACTIVATION_QUANT_MAX,
            "output_scale": OUTPUT_SCALE,
            "max_abs_weight": MAX_ABS_QUANT_WEIGHT,
        },
    }
    metadata_bytes = canonical_json_bytes(training_metadata)
    metadata_hash = hashlib.sha256(metadata_bytes).digest()
    (args.output_dir / "training-metadata.json").write_bytes(metadata_bytes)

    blob = build_network_blob(model, metadata_hash)
    network_path = args.output_dir / f"nnue-{args.hidden}-v1.nnue"
    network_path.write_bytes(blob)

    export_manifest = {
        "schema_version": 1,
        "network": network_path.name,
        "network_sha256": hashlib.sha256(blob).hexdigest(),
        "network_bytes": len(blob),
        "training_metadata": "training-metadata.json",
        "training_metadata_sha256": metadata_hash.hex(),
        "payload_checksum_fnv1a64": f"0x{fnv1a64(blob[HEADER_LEN:]):016x}",
    }
    (args.output_dir / "export-manifest.json").write_bytes(canonical_json_bytes(export_manifest))
    print(json.dumps(export_manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
