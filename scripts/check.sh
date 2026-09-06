#!/usr/bin/env sh
set -eu

python3 -m unittest discover -s tests -p 'test_match_harness.py'
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-features
cargo test --workspace --all-features --release
cargo run --release --quiet -p chess-bench
