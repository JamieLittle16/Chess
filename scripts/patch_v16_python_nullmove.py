#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

BLOCK = r'''

    # V16 null-move pilot. This is deliberately conservative: deep scout nodes only, both sides
    # retain non-pawn material, no EP transition, no check, no mate-boundary score and no recent
    # 50-move pressure. A null child is a search artefact, so repetition/50-move history is reset
    # for the probe and consecutive null moves are forbidden by the reversible position-key test.
    previous_was_null = (
        ply > 0 and path_keys[ply - 1] == (current_key ^ REPETITION_SIDE_KEY)
    )
    if (
        depth >= 6
        and scout_node
        and not checked
        and not previous_was_null
        and ep_square < 0
        and halfmove_clock < 80
        and abs(beta) < MATE_THRESHOLD
        and _has_nonpawn_material(board, side)
        and _has_nonpawn_material(board, -side)
    ):
        null_static = _evaluate_state_classical(side, eval_stack[ply])
        if null_static >= beta + 80:
            # Lazy H64 state must be coherent before creating an identity (pass) edge.
            _materialize_student_path(eval_stack, student_edges, ply)
            for null_i in range(EVAL_WIDTH):
                eval_stack[ply + 1, null_i] = eval_stack[ply, null_i]
            student_edges[ply + 1] = np.uint64(0)
            path_keys[ply + 1] = current_key ^ REPETITION_SIDE_KEY
            history_contexts[ply + 1] = np.uint64(0xD1B54A32D192ED03)
            null_reduction = 2 + depth // 4
            null_depth = max(0, depth - 1 - null_reduction)
            null_child, null_aborted = _negamax(
                board,
                -side,
                castling,
                -1,
                0,
                null_depth,
                -beta,
                -beta + 1,
                ply + 1,
                nodes,
                max_nodes,
                hard_deadline_ticks,
                pseudo_stack,
                move_stack,
                score_stack,
                eval_stack,
                history_keys,
                history_count,
                path_keys,
                killers,
                lmr_history,
                hash_keys,
                hash_moves,
                history_contexts,
                student_edges,
                tt_table,
            )
            if null_aborted:
                return 0, True
            null_score = -null_child
            if null_score >= beta:
                return null_score, False
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('path', type=Path)
    args = ap.parse_args()
    s = args.path.read_text()
    marker = '''    checked = _state_in_check(board, side, eval_stack[ply])\n    # Conservative reverse-futility pruning ported from the accepted Rust policy.'''
    if marker not in s:
        raise SystemExit('negamax insertion marker missing')
    s = s.replace(
        marker,
        '    checked = _state_in_check(board, side, eval_stack[ply])' + BLOCK + '\n\n    # Conservative reverse-futility pruning ported from the accepted Rust policy.',
        1,
    )
    if s.count('V16 null-move pilot') != 1:
        raise SystemExit('unexpected null-move patch multiplicity')
    args.path.write_text(s)
    print('patched conservative V16 null-move pilot')


if __name__ == '__main__':
    main()
