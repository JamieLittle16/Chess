#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

WRAPPER_BLOCK = r'''

@njit(cache=False)
def _q_advance_eval_state_into(
    board: np.ndarray,
    side: int,
    move: int,
    parent: np.ndarray,
    child: np.ndarray,
) -> None:
    _advance_eval_state_into(board, side, move, parent, child)


@njit(cache=False)
def _q_child_position_key(
    board_after: np.ndarray,
    side_moved: int,
    old_castling: int,
    old_ep: int,
    move: int,
    child_castling: int,
    child_ep: int,
    captured_piece: int,
    captured_square: int,
    parent_key: np.uint64,
) -> np.uint64:
    return _child_position_key(
        board_after, side_moved, old_castling, old_ep, move,
        child_castling, child_ep, captured_piece, captured_square, parent_key,
    )


@njit(cache=False)
def _q_legal_moves_for_state(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    pseudo: np.ndarray,
    moves: np.ndarray,
    state: np.ndarray,
) -> int:
    return _legal_moves_for_state(board, side, castling, ep_square, pseudo, moves, state)
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('path', type=Path)
    ap.add_argument('--variant', choices=('q-eval', 'q-eval-key', 'q-state', 'q-state-store'), required=True)
    args = ap.parse_args()

    s = args.path.read_text()
    q_marker = '@njit(cache=False)\ndef _quiescence('
    if q_marker not in s:
        raise SystemExit('missing qsearch marker')
    for name in ('_advance_eval_state_into', '_child_position_key', '_legal_moves_for_state'):
        inline = f'@njit(cache=False, inline="always")\ndef {name}('
        if inline not in s:
            raise SystemExit(f'{name} is not still forced-inline; refuse ambiguous patch')

    s = s.replace(q_marker, WRAPPER_BLOCK + '\n\n' + q_marker, 1)
    start = s.index(q_marker)
    next_decorator = s.index('\n\n@njit(', start + len(q_marker))
    qbody = s[start:next_decorator]

    replacements = {'q-eval': ('_advance_eval_state_into',),
                    'q-eval-key': ('_advance_eval_state_into', '_child_position_key'),
                    'q-state': ('_advance_eval_state_into', '_child_position_key', '_legal_moves_for_state'),
                    'q-state-store': ('_advance_eval_state_into', '_child_position_key', '_legal_moves_for_state')}[args.variant]
    mapping = {
        '_advance_eval_state_into': '_q_advance_eval_state_into',
        '_child_position_key': '_q_child_position_key',
        '_legal_moves_for_state': '_q_legal_moves_for_state',
    }
    counts = {}
    for old in replacements:
        counts[old] = qbody.count(old + '(')
        if counts[old] == 0:
            raise SystemExit(f'no qsearch calls found for {old}')
        qbody = qbody.replace(old + '(', mapping[old] + '(')
    s = s[:start] + qbody + s[next_decorator:]

    if args.variant == 'q-state-store':
        anchor = '@njit(cache=False, inline="always")\ndef _qsearch_tt_store('
        if anchor not in s:
            raise SystemExit('missing forced-inline qTT store')
        s = s.replace(anchor, '@njit(cache=False)\ndef _qsearch_tt_store(', 1)

    args.path.write_text(s)
    print('VARIANT', args.variant)
    print('QSEARCH_REPLACEMENTS', counts)
    print('MAIN_INLINE_ADVANCE', s.count('@njit(cache=False, inline="always")\ndef _advance_eval_state_into('))
    print('MAIN_INLINE_KEY', s.count('@njit(cache=False, inline="always")\ndef _child_position_key('))
    print('MAIN_INLINE_LEGAL', s.count('@njit(cache=False, inline="always")\ndef _legal_moves_for_state('))


if __name__ == '__main__':
    main()
