#!/usr/bin/env python3
"""Avoid both learned-evaluator child updates for late quiets that futility-prune.

Apply after patch_v16_python_rust_history.py.  The futility predicate depends only on parent/node
state and move metadata, so it can be known before any child evaluator update.  For such a move we
make the board move first and test check directly against the opponent king square carried by the
parent's exact classical state.  A non-checking candidate is immediately unmade without touching
V13 residual or H64 student state.  A rare checking survivor rebuilds the exact child evaluator
state from the already-made board.  All other moves retain the original incremental path.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_python_defer_futility_all.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

old = '''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        path_keys[ply + 1] = _child_position_key(
            board,
            side,
            castling,
            ep_square,
            move,
            child_castling,
            child_ep,
            captured_piece,
            captured_square,
            path_keys[ply],
        )
        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, child_halfmove
        )

        # Adaptive verified LMR v3. Captures/promotions, both killers, checks, nodes in check and
        # the defender-safe immediate promotion threat are never reduced. The deeper R2/R3 bands
        # only apply to genuinely late quiets. Any reduced alpha raise is verified at full depth.
        lmr_candidate = not checked and quiet and not protected_killer
        move_history_score = _quiet_history_score(side, previous_context, current_move_context, quiet_history)
        reduction = _history_adjusted_lmr_reduction(depth, index, move_history_score) if lmr_candidate else 0
        futility_candidate = (
            pruning_static_eval != INFINITY
            and depth <= 2
            and index >= 4
            and quiet
            and not protected_killer
            and abs(alpha) < MATE_THRESHOLD
            and pruning_static_eval + 180 * depth <= alpha
        )
        # Check status only matters when this quiet could actually be reduced or pruned. Avoiding
        # the attack test for early/non-reduced quiets preserves exact search semantics while
        # removing work from one of the hottest recursive paths.
        need_gives_check = lmr_candidate and (reduction > 0 or futility_candidate)
        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False
        # Accepted Rust late-quiet futility on top of submission-V11 recursive semantics. The shared
        # static eval exists only on the same conservative scout
        # nodes as RFP. We have already made the move so gives_check is exact; skipped moves are
        # immediately unmade and never enter TT/killer state.
        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue
'''
new = '''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)

        # Adaptive verified LMR v3 plus accepted Rust history conditioning.  Work out the late-quiet
        # futility predicate before touching child evaluator state: every input is parent/node data.
        lmr_candidate = not checked and quiet and not protected_killer
        move_history_score = _quiet_history_score(side, previous_context, current_move_context, quiet_history)
        reduction = _history_adjusted_lmr_reduction(depth, index, move_history_score) if lmr_candidate else 0
        futility_candidate = (
            pruning_static_eval != INFINITY
            and depth <= 2
            and index >= 4
            and quiet
            and not protected_killer
            and abs(alpha) < MATE_THRESHOLD
            and pruning_static_eval + 180 * depth <= alpha
        )

        if futility_candidate:
            # Do not compute V13 residual or H64 child state yet.  The opponent king cannot move on
            # our turn, so check is exact from the made board plus its square in the parent state.
            child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
                board, side, castling, ep_square, move
            )
            opponent_king = int(
                eval_stack[ply, EVAL_BLACK_KING] if side == WHITE else eval_stack[ply, EVAL_WHITE_KING]
            )
            gives_check = opponent_king < 0 or is_square_attacked(board, opponent_king, side)
            if not gives_check:
                undo_move_inplace(board, side, move, captured_piece, captured_square)
                continue
            # Checking late quiets are deliberately exempt from futility.  They are rare here; an
            # exact rebuild is simpler and safer than reconstructing king-bucket residual deltas
            # from a board that has already changed.
            _build_eval_state_into(board, eval_stack[ply + 1])
        else:
            _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
            child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
                board, side, castling, ep_square, move
            )
            need_gives_check = lmr_candidate and reduction > 0
            gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False

        path_keys[ply + 1] = _child_position_key(
            board,
            side,
            castling,
            ep_square,
            move,
            child_castling,
            child_ep,
            captured_piece,
            captured_square,
            path_keys[ply],
        )
        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, child_halfmove
        )
'''
if s.count(old) != 1:
    raise SystemExit(f"late-quiet learned-state anchor count={s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s)
print('deferred V13 residual + H64 state for futility candidates; pruned quiets pay neither update')
