#!/usr/bin/env bash
set -euo pipefail
OUT="${1:-/tmp/v13}"
cat .analysis/v13_chunks_*.b64 | base64 -d > /tmp/v13-base.zip
echo '658fd954180c2d0d39c02ba6601af36d06cdbd573bfb72c6879169861a7ad092  /tmp/v13-base.zip' | sha256sum -c -
rm -rf "$OUT"
mkdir -p "$OUT"
unzip -q /tmp/v13-base.zip -d "$OUT"
echo "5f78be45580bd184e4c3399433fe678cf665c3cbd1edfc4f8e3d508ccff661da  $OUT/experiments/numba_search.py" | sha256sum -c -
echo "7d0fc5f7a186e79317cf12a2ff285d7716c651fbd045c53d65a3cc6eb1b15319  $OUT/experiments/v13_residual.i16" | sha256sum -c -
patch "$OUT/experiments/numba_search.py" < .analysis/v13_jit_refactor.patch
echo "276636ffa41a89cf21d3886d330f5158994ac01f534e4a718a15d41a588f4bf0  $OUT/experiments/numba_search.py" | sha256sum -c -
