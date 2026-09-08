#!/usr/bin/env python3
"""Execute the compact-history patch with indentation-independent negamax call rewriting.

The underlying patch was intentionally written against exact packaged V14, but recursive/root call
sites use two indentation levels.  Replace only that assembler fragment before executing it so all
seven child-search calls receive the tiny history table without weakening any other anchor checks.
"""
from pathlib import Path

source_path = Path(__file__).with_name("patch_v15_python_compact_history.py")
source = source_path.read_text()
start_marker = "# Four recursive calls inside _negamax use this exact tail.\n"
end_marker = "# One tiny table lives for the whole iterative-deepening call, preserving information between depths.\n"
start = source.index(start_marker)
end = source.index(end_marker, start)
replacement = r'''# All four recursive and three root child-search calls share this argument line; indentation differs.
call_tail = "path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,"
count = s.count(call_tail)
if count != 7:
    raise SystemExit(f"negamax call-tail count={count} expected=7")
s = s.replace(call_tail, call_tail[:-1] + ", main_history,")

rep(
    ''' + "'''        undo_move_inplace(board, side, move, captured_piece, captured_square)\\n        if score > best_score:\\n'''" + r''',
    ''' + "'''        undo_move_inplace(board, side, move, captured_piece, captured_square)\\n        if quiet and beta == alpha_original + 1 and history_piece >= 0:\\n            bonus = _main_history_bonus(depth)\\n            if score < beta:\\n                bonus = -(bonus // 2)\\n            _update_main_history(main_history, side, history_piece, move_to(move), bonus)\\n        if score > best_score:\\n'''" + r''',
    1,
    "history training",
)

'''
source = source[:start] + replacement + source[end:]
exec(compile(source, str(source_path), "exec"), {"__name__": "__main__", "__file__": str(source_path)})
