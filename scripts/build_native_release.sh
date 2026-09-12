#!/usr/bin/env bash
set -euo pipefail

# Build the native tournament/desktop binary using the portable release profile's
# fat LTO + single codegen unit while allowing LLVM to use the host CPU ISA.
# Keep these flags out of the workspace-wide Cargo config so WASM and portable
# release builds remain deployable on older machines.
export RUSTFLAGS="${RUSTFLAGS:+${RUSTFLAGS} }-C target-cpu=native -C target-feature=+popcnt"

cargo build --release -p chess-uci

echo "native release: target/release/chess-uci"
