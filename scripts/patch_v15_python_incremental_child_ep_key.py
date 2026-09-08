#!/usr/bin/env python3
"""Avoid a full 64-square repetition-key rebuild on every new en-passant target.

The V14 child-key path falls back to position_key whenever either the old or child position has an
EP square.  A *new* EP square is easy to handle exactly: all ordinary piece/castling/side changes
remain incremental, then the EP Zobrist key is added iff the child really has a legal EP capture.
Only old_ep still needs the conservative rebuild because parent_key does not record whether its EP
square was repetition-relevant.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
old='''    # EP state is rare and its repetition relevance depends on king-safety legality.  Recompute
    # the child key on EP transitions rather than maintaining a fragile incremental special case.
    if old_ep >= 0 or child_ep >= 0:
        return position_key(board_after, -side_moved, child_castling, child_ep)

    key = parent_key ^ REPETITION_SIDE_KEY
'''
new='''    # If the parent already had an EP square we cannot tell from parent_key alone whether it was
    # repetition-relevant, so preserve the conservative rebuild.  A newly-created EP target needs
    # no rebuild: maintain the ordinary key incrementally and add the EP component only when a legal
    # child capture exists (the exact same condition used by position_key).
    if old_ep >= 0:
        return position_key(board_after, -side_moved, child_castling, child_ep)

    key = parent_key ^ REPETITION_SIDE_KEY
'''
if s.count(old)!=1: raise SystemExit(f'EP fallback anchor count={s.count(old)}')
s=s.replace(old,new,1)
old2='''        key ^= REPETITION_PIECE_KEYS[rook_index, rook_from]
        key ^= REPETITION_PIECE_KEYS[rook_index, rook_to]
    return key
'''
new2='''        key ^= REPETITION_PIECE_KEYS[rook_index, rook_from]
        key ^= REPETITION_PIECE_KEYS[rook_index, rook_to]

    if child_ep >= 0 and _has_legal_en_passant(board_after, -side_moved, child_ep):
        key ^= REPETITION_EP_KEYS[child_ep]
    return key
'''
if s.count(old2)!=1: raise SystemExit(f'child-key return anchor count={s.count(old2)}')
s=s.replace(old2,new2,1)
p.write_text(s)
