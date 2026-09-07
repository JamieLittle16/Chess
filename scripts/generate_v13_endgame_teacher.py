#!/usr/bin/env python3
"""Generate grouped Stockfish teacher data only for low-phase reached positions.

The split unit remains the canonical opening root from generate_nnue_teacher_data, so positions
from the same game/opening cannot leak across train/validation/holdout. Filtering happens before
Stockfish analysis, making this substantially cheaper than relabelling the full V13 corpus.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import chess

from generate_nnue_teacher_data import canonical_root_group, deterministic_split, pgn_positions
from stockfish_lab import StockfishTeacher, sha256_file, write_json

PHASE = (0, 0, 1, 1, 2, 4, 0)


def material_phase(board: chess.Board) -> int:
    return sum(PHASE[p.piece_type] for p in board.piece_map().values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stockfish', type=Path, required=True)
    ap.add_argument('--pgn', type=Path, required=True)
    ap.add_argument('--nodes', type=int, default=12000)
    ap.add_argument('--threads', type=int, default=1)
    ap.add_argument('--hash-mb', type=int, default=64)
    ap.add_argument('--min-ply', type=int, default=20)
    ap.add_argument('--max-ply', type=int, default=220)
    ap.add_argument('--max-phase', type=int, default=8)
    ap.add_argument('--max-positions', type=int, default=8000)
    ap.add_argument('--validation-permille', type=int, default=100)
    ap.add_argument('--holdout-permille', type=int, default=100)
    ap.add_argument('--split-salt', default='Chess/v13-endgame-v1')
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    source_sha = sha256_file(args.pgn)
    output_path = args.output_dir / 'teacher.jsonl'
    split_counts: Counter[str] = Counter()
    phase_counts: Counter[int] = Counter()
    group_counts: Counter[str] = Counter()
    considered = 0
    written = 0

    with StockfishTeacher(args.stockfish, nodes=args.nodes, threads=args.threads, hash_mb=args.hash_mb) as teacher, output_path.open('w', encoding='utf-8') as output:
        teacher_manifest = teacher.manifest()
        for group, source_position, board in pgn_positions(args.pgn, source_sha, args.min_ply, args.max_ply):
            considered += 1
            phase = material_phase(board)
            if phase > args.max_phase:
                continue
            analysis = teacher.analyse(board, pov=board.turn)
            split = deterministic_split(group, salt=args.split_salt, validation=args.validation_permille, holdout=args.holdout_permille)
            record = {
                'schema_version': 1,
                'group': group,
                'source_position': source_position,
                'split': split,
                'fen': board.fen(),
                'phase': phase,
                'side_to_move': 'white' if board.turn == chess.WHITE else 'black',
                'ply': board.ply(),
                'teacher_cp': analysis.score.cp,
                'teacher_mate': analysis.score.mate,
                'teacher_expectation': round(analysis.score.expectation, 6),
                'teacher_wins': analysis.score.wins,
                'teacher_draws': analysis.score.draws,
                'teacher_losses': analysis.score.losses,
                'teacher_best_move': analysis.best_move,
                'teacher_depth': analysis.depth,
                'teacher_seldepth': analysis.seldepth,
                'teacher_nodes': analysis.nodes,
                'teacher_nps': analysis.nps,
                'teacher_pv': list(analysis.pv),
            }
            output.write(json.dumps(record, sort_keys=True) + '\n')
            split_counts[split] += 1
            phase_counts[phase] += 1
            group_counts[group] += 1
            written += 1
            if written >= args.max_positions:
                break

    manifest = {
        'schema_version': 1,
        'source': {'kind': 'pgn', 'path': str(args.pgn.resolve()), 'sha256': source_sha},
        'teacher': teacher_manifest,
        'selection': {
            'min_ply': args.min_ply,
            'max_ply': args.max_ply,
            'max_phase': args.max_phase,
            'max_positions': args.max_positions,
        },
        'split': {
            'salt': args.split_salt,
            'validation_permille': args.validation_permille,
            'holdout_permille': args.holdout_permille,
            'assignment_unit': 'canonical opening root',
        },
        'positions_considered': considered,
        'positions_written': written,
        'groups_written': len(group_counts),
        'largest_group_positions': max(group_counts.values(), default=0),
        'split_counts': dict(sorted(split_counts.items())),
        'phase_counts': {str(k): v for k, v in sorted(phase_counts.items())},
        'output': output_path.name,
    }
    write_json(args.output_dir / 'manifest.json', manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
