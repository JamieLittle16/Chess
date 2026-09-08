# Python V16 strength programme

## Measured calibration

Clean Python candidate (`V14 + trusted continuity + stable presort`) versus production Rust V15 + Gestalt v85, 64 paired 2.5+0.05 wall-clock games on fresh UHO roots:

- Python score: 7.0 / 64 = 10.9375%
- Naive Elo from score: -364.31
- Python mean move time: 76.59 ms
- Rust mean move time: 91.71 ms

The gap is therefore primarily chess quality per unit time, not Python wall-clock overhead.

## Search-leaf Gestalt distillation

A corpus of 129,952 real Rust V15 search evaluation leaves was labelled with exact Gestalt v85. Compact king-bucket students trained on that search distribution reduce holdout RMSE from ~367 cp for packaged V14 to:

- H16: 188.91 cp
- H24: 188.24 cp

H16 is the first runtime candidate because H24 adds 50% more accumulator lanes for negligible holdout improvement.

Runtime qualification requires exact trainer/runtime feature-index parity, incremental-state parity including castling/en-passant/promotion/king-bucket changes, fixed-node throughput, equal-node chess, and competition-clock chess before promotion.
