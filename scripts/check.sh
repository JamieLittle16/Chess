#!/usr/bin/env sh
set -eu

python3 -m unittest discover -s tests -p 'test_*.py'
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --workspace --all-features --no-deps
cargo test --workspace --all-features
cargo test --workspace --all-features --release
cargo test --release -p chess-core --test core_qualification deep_perft_qualification -- --ignored --exact
cargo run --release --quiet -p chess-bench
