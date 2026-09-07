#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 TARGET_DIR" >&2
  exit 2
fi

TARGET="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_ZIP="$(mktemp)"
trap 'rm -f "$BASE_ZIP"' EXIT

cat "$ROOT"/.analysis/v13_chunks_*.b64 | base64 -d > "$BASE_ZIP"
echo '658fd954180c2d0d39c02ba6601af36d06cdbd573bfb72c6879169861a7ad092  '"$BASE_ZIP" | sha256sum --check --strict

rm -rf "$TARGET"
mkdir -p "$TARGET"
unzip -q "$BASE_ZIP" -d "$TARGET"
patch "$TARGET/experiments/numba_search.py" < "$ROOT/.analysis/v13_jit_refactor.patch"

TARGET="$TARGET" python - <<'PY'
import os
from pathlib import Path

p = Path(os.environ["TARGET"]) / "experiments/numba_search.py"
s = p.read_text()
old = '    return score + correction\n\n\n@njit(cache=False, inline="never")\ndef _advance_residual_state_into('
new = '    correction = correction // 6\n    return score + correction\n\n\n@njit(cache=False, inline="never")\ndef _advance_residual_state_into('
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, new, 1))
PY

python "$ROOT/scripts/patch_v13_legality_context.py" "$TARGET/experiments/numba_core.py"
python "$ROOT/scripts/patch_v13_qsearch_tactical.py" \
  "$TARGET/experiments/numba_core.py" "$TARGET/experiments/numba_search.py"

python -m py_compile "$TARGET/agent.py" "$TARGET"/experiments/*.py

echo 'df346b21be42832a0ae97e7faa15953ab460f0387fb0358961651466557ebde8  '"$TARGET/agent.py" | sha256sum --check --strict
echo '0306e8145a453d91b9b5ac92e9980931510d9e18f8ba598a7548d08b85165c35  '"$TARGET/experiments/numba_core.py" | sha256sum --check --strict
echo '401f6580028a72361286bd99bee1f0022c74e6c8a65da8acd47448835a1ff360  '"$TARGET/experiments/numba_search.py" | sha256sum --check --strict
echo '7d0fc5f7a186e79317cf12a2ff285d7716c651fbd045c53d65a3cc6eb1b15319  '"$TARGET/experiments/v13_residual.i16" | sha256sum --check --strict
