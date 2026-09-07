#!/usr/bin/env bash
set -euo pipefail
OUT="${1:-/tmp/v12}"
cat .analysis/v11_chunks_*.b64 | base64 -d > /tmp/v11-original.zip
echo 'fd06e9f5718b9af3be3b13f8d6b67f92018b43ce2f2cb991063d2a281310d0b8  /tmp/v11-original.zip' | sha256sum -c -
rm -rf "$OUT"
mkdir -p "$OUT"
unzip -q /tmp/v11-original.zip -d "$OUT"
python - "$OUT" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1]) / 'experiments/numba_search.py'
s = p.read_text()
old = '''        # Conservative verified LMR. Only an immediate seventh-rank promotion threat is exempt;\n        # sixth-rank pushes are ordinary quiets again. Checks are still never reduced, and every\n        # reduced alpha improvement is verified at full depth.\n        promotion_threat = _quiet_pawn_relative_rank(board, move) == 6\n        lmr_candidate = (\n            depth >= 3\n            and index >= 3\n            and not checked\n            and not promotion_threat\n            and order_score < 5_040_000\n        )\n        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if lmr_candidate else False\n        reduce = lmr_candidate and not gives_check\n        search_depth = depth - 2 if reduce else depth - 1\n        if promotion_threat and depth == 1:\n            # Repair exactly the V10 horizon asymmetry. At depth 1 this quiet push would otherwise\n            # fall directly into qsearch; keep one normal-search ply so the defender may choose ANY\n            # legal reply. Depth >= 2 already contains that defender reply and is not extended.\n            search_depth = depth\n'''
new = '''        # Conservative verified LMR. Promotion verification is intentionally ROOT-ONLY:\n        # enabling the seventh-rank extension throughout the recursive tree consumed too much\n        # search budget and regressed strength. Recursive quiet pawn pushes therefore follow the\n        # same proven V11 reduction policy as other quiet moves. Checks are still never reduced,\n        # and every reduced alpha improvement is verified at full depth.\n        lmr_candidate = (\n            depth >= 3\n            and index >= 3\n            and not checked\n            and order_score < 5_040_000\n        )\n        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if lmr_candidate else False\n        reduce = lmr_candidate and not gives_check\n        search_depth = depth - 2 if reduce else depth - 1\n'''
assert old in s
s = s.replace(old, new, 1)
old = '''        if alpha >= beta:\n            # A seventh-rank threat already has its dedicated priority/extension and must not occupy\n            # a generic killer slot.\n            if not promotion_threat and order_score < 5_590_000:\n'''
new = '''        if alpha >= beta:\n            # Preserve the proven V11 recursive killer policy. Root-only promotion verification\n            # deliberately does not change recursive killer semantics.\n            if order_score < 5_590_000:\n'''
assert old in s
s = s.replace(old, new, 1)
old = '''        if depth == 1 and _quiet_pawn_relative_rank(board, move) == 6:\n            # Root preferred moves live in the 10M ordering band, so classify the rare horizon case\n            # directly rather than inferring it from order_score.\n            child_depth = depth\n'''
new = '''        if depth == 1 and _quiet_pawn_relative_rank(board, move) == 6:\n            # Deliberately root-only: verify an immediate quiet seventh-rank push with one complete\n            # defender reply, but do not recursively extend analogous pushes deeper in the tree.\n            # This keeps the useful V10 horizon repair without globally biasing search effort.\n            child_depth = depth\n'''
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)
PY
echo "3191c46f19a1c0b159de0fe5146bbc0bd3dcb74755619838084b3f87f299331f  $OUT/experiments/numba_search.py" | sha256sum -c -
(cd "$OUT" && patch -p0 < "$GITHUB_WORKSPACE/.analysis/v11_to_v12_numba_search.patch")
echo "2551275ca1767610d2546683b75aaae1bee794d400d7c082efcdf7b7ea2be2fd  $OUT/experiments/numba_search.py" | sha256sum -c -
