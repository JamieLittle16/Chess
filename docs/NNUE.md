# Incremental Learned Evaluation Programme

Status: **M5 architecture v1**

The production classical evaluator remains the permanent control. Learned evaluation is introduced as
an additional replaceable implementation and must earn production through equal-time games.

## 1. Objective

The current search is substantially more mature than its positional representation. M5 therefore
builds a very cheap learned value model capable of representing interactions that the current
material/PSQT/bishop-pair/rook-file evaluator cannot express economically.

The target is not the lowest validation loss. The target is:

> **maximum equal-time Elo per unit of inference/update cost**.

Native and WASM deployment are both first-class constraints.

## 2. Architectural boundary

`chess-core` continues to own legal chess only. It must not gain neural weights or model policy.

Learned state belongs to evaluation/search state:

```text
Position (chess truth)
    +
EvaluatorState (derived, disposable)
    +
Search stack
```

A position can always reconstruct evaluator state from scratch. Incremental state is a performance
cache, not chess truth.

The initial production-facing evaluator boundary should remain statically dispatched/monomorphisable;
do not put dynamic dispatch into every searched leaf merely for architectural neatness.

## 3. First feature family

Start with a sparse king-relative piece-square representation rather than a dense board tensor.

For each perspective, an active feature identifies approximately:

```text
perspective king bucket
x
piece ownership relative to perspective
x
piece kind
x
piece square
```

Important properties:

- only a few features change after an ordinary move;
- capture removes one feature;
- promotion replaces the pawn feature with the promoted piece feature;
- castling updates king and rook geometry;
- en-passant removes the captured pawn from its actual square;
- a king-bucket change may refresh that perspective's accumulator;
- White/Black perspective accumulators are independent.

The precise king-bucket count is an experiment. Do not freeze HalfKP dimensions merely because another
engine uses them.

## 4. Accumulator contract

The first correctness milestone is independent of trained weights.

Implement both:

```text
slow oracle: active features rebuilt from Position
fast path:   feature delta derived from (pre-move Position, ChessMove)
```

Then prove by randomized legal play:

```text
apply incremental delta
==
rebuild active features from resulting Position
```

after every move, and likewise after every unmake.

Only once feature deltas are trustworthy should they update hidden neural accumulators.

### Stack ownership

Search already owns a reversible position stack. The learned evaluator should use a parallel fixed-size
or stack-local reversible state. No heap allocation is permitted per recursive move.

A move's evaluation undo record should contain only information that cannot be cheaply inferred during
unmake. Prefer compact deltas and perspective-refresh markers over copying full accumulators at every
ply.

## 5. First network ladder

Do not begin with one large network. Train a predetermined ladder such as:

```text
Tiny:    sparse input -> 32  hidden -> scalar
Small:   sparse input -> 64  hidden -> scalar
Medium:  sparse input -> 128 hidden -> scalar
```

The exact dimensions can change after measurement. The point is to establish a cost/strength frontier.

For every size record:

- serialized bytes;
- full-refresh latency;
- ordinary sparse-update latency;
- scalar inference latency;
- engine NPS;
- completed iterative depth under time control;
- validation CP/WDL loss;
- equal-time Elo.

A larger model is rejected if its extra positional accuracy does not repay lost search.

## 6. Quantized inference

The intended production path is integer inference:

```text
quantized input weights
-> int16/int32 accumulator
-> clipped activation
-> quantized output weights
-> int32 score
-> engine score scale
```

Requirements:

- no floating point required in the recursive hot path;
- SIMD-friendly contiguous layout;
- scalar reference implementation retained for correctness;
- deterministic inference for a fixed network file;
- explicit overflow bounds documented and tested;
- WASM SIMD path shares the same network semantics.

Do not introduce unsafe SIMD initially. A later unsafe implementation requires the project's normal ADR,
measurement and safe-reference discipline.

## 7. Network file format

Weights are derived artifacts and must be independently identifiable. The first format should contain:

```text
magic
format version
feature-set id/version
network dimensions
quantization scales
weight/bias arrays
payload checksum
training metadata hash/reference
```

The engine must reject incompatible/corrupt files rather than silently interpreting them under a new
feature mapping.

For tournament builds we may eventually embed an accepted network, but the on-disk format should exist
first so experiments are reproducible.

## 8. Teacher targets

Use full-strength Stockfish at a fixed node budget. Retain both:

- centipawn/mate-like score;
- WDL expectation.

The training objective should initially test a small number of predetermined target mixtures rather
than endlessly tune loss weights. WDL is especially important because equal CP errors have very
different game-value impact in equal versus already-winning positions.

Data generation is implemented by `scripts/generate_nnue_teacher_data.py` and specified in
`docs/STRENGTH_LAB.md`.

## 9. Data diversity

The first serious corpus should contain millions of positions drawn from several independently
identified sources:

- frozen UHO opening positions plus continuations;
- our engine's self-play at varied strengths/budgets;
- games against stronger engines;
- strong-engine positions where provenance/licensing permits;
- tactical middlegames;
- quiet manoeuvring positions;
- pawn and rook endings;
- minor-piece endings;
- king/pawn races;
- imbalanced material.

Do not oversample only positions where the current engine already plays. That would teach the model its
own search distribution too narrowly.

## 10. Split discipline

Train/validation/holdout separation happens by source group, especially by **whole game**. Position-level
random splitting is forbidden for game-derived data because adjacent positions are highly correlated.

Keep at least one holdout corpus from a source family not used for ordinary hyperparameter selection.

## 11. Search interaction programme

An accepted NNUE changes the reliability of static-eval-dependent pruning. After the evaluator itself
wins, re-qualify search mechanisms one at a time.

High-priority retests:

1. reverse-futility margin;
2. late-quiet futility margin;
3. LMR schedule/history conditioning;
4. quiet history;
5. continuation history;
6. correction history;
7. verified null-move pruning;
8. singular extensions.

Old constants are not sacred. Equally, do not tune all of them simultaneously and lose causal
measurement.

## 12. Policy comes later

The first learned milestone is a scalar value evaluator. A policy head is a separate experiment because
policy inference can cost enough to reduce calculation depth.

Once value is accepted, a compact policy may guide:

- root ordering;
- late quiet ordering;
- LMR reduction decisions;
- selective search effort.

Objective alpha-beta scores remain authoritative.

## 13. Acceptance ladder

A learned evaluator moves through these gates:

```text
feature-delta correctness
full/incremental equality over long randomized sequences
network serialization/hash tests
scalar-vs-optimized inference equality
latency/NPS benchmark
fixed-depth tactical/draw regressions
100-game paired equal-time screen
fresh-seed >=200-game acceptance
holdout opening suite when borderline/large
external Stockfish recalibration
```

Do not relax the match threshold because training metrics look convincing.

## 14. Immediate implementation slices

### NNUE-1 — sparse feature delta substrate

- versioned king-relative feature mapper;
- ordinary move/capture/promotion/en-passant/castle deltas;
- king-move refresh marker;
- slow active-feature oracle;
- randomized make/unmake differential tests.

### NNUE-2 — tiny scalar network

- deterministic network format;
- slow full evaluation;
- training/export script;
- no production search integration yet.

### NNUE-3 — incremental hidden accumulator

- sparse add/subtract updates;
- refresh on king-bucket changes;
- fixed search-stack undo integration;
- slow-rebuild oracle after every random move/unmove.

### NNUE-4 — equal-time qualification ladder

Train Tiny/Small/Medium from the same frozen dataset and compare Elo per nanosecond.

Only the winner proceeds to search retuning.
