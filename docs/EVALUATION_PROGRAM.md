# Evaluation Programme

Status: design contract for M4/M5 evaluation work.

## Objective

Evaluation exists to maximise equal-time playing strength, not standalone prediction quality. Every evaluator candidate is therefore judged by the combined effect of chess knowledge and inference cost.

The primary acceptance metric is paired-game Elo under a fixed wall-clock protocol. Supporting measurements are inference latency, NPS, average completed depth, static-evaluation count, accumulator update/refresh cost, and validation loss when a learned model is involved.

## Governing principle

For evaluator `E`, model quality is not the objective in isolation:

```text
better position estimate
        -
search throughput lost to obtain it
        =
equal-time playing strength
```

A more accurate evaluator that costs a full search ply and loses Elo is rejected.

## Classical ladder

The current reference evaluator is material-only. The first positional programme should remain cheap and ablatable.

### E0 — material

Accepted permanent control. No positional terms.

### E1 — tapered material + piece-square placement

Introduce a material-derived phase and middle-game/end-game score pair. Piece-square terms should be table lookups over existing bitboards. This creates the tapered-evaluation substrate without expensive structural analysis.

A conventional interpolation is acceptable as a transparent first baseline:

`score = (phase * mg + (MAX_PHASE - phase) * eg) / MAX_PHASE`.

The exact phase scale and tables are parameters to qualify, not doctrine.

### E2 — mobility

Add cheap pseudo-legal/attack mobility where possible, avoiding full legal move generation from evaluation. Measure its direct cost and whether search depth falls.

### E3 — pawn structure

Candidate terms include doubled, isolated, connected and passed pawns. Prefer bitboard masks/precomputed file/rank relations over per-square branching. Passed-pawn bonuses should be phase/rank aware.

### E4 — minor/rook structure

Candidate terms include bishop pair, rook open/semi-open files, and lightweight activity features. Each term is tested as an isolated delta from the last accepted evaluator.

### E5 — king safety / endgame king activity

Keep the first king model intentionally compact. Expensive attack-map reconstruction is not justified unless equal-time games pay for it.

No group of terms is accepted merely because it is conventional chess knowledge. Each material change must pass a paired-game screen.

## Incremental architecture

The long-term evaluator boundary must support reversible search without board cloning or heap allocation.

Target conceptual interface:

```text
Evaluator accumulator
    ├── push(move delta)
    ├── pop(move delta)
    ├── refresh(position, perspective)
    └── evaluate(position context)
```

The exact Rust API should be chosen only when the first incremental candidate is implemented; do not force `chess-core` to depend on evaluator policy.

Classical E1 may initially recompute from bitboards if that is already cheap enough. Incrementalisation itself must earn its complexity through measured latency/NPS improvement. This avoids prematurely coupling chess correctness and intelligence.

## Learned ladder

The first learned evaluator should be deliberately small.

```text
L0  accepted classical evaluator
L1  tiny learned scalar value
L2  sparse incremental value
L3  king-relative incremental value experiment
L4  value + cheap policy
L5  value + policy + uncertainty
```

HalfKP/HalfKA-style king-relative sparse features are experiments, not architectural requirements.

For every learned candidate record at least:

- held-out prediction loss / calibration;
- full-refresh inference time;
- incremental update time;
- king-move refresh cost for king-relative models;
- NPS and evaluation calls/second;
- average completed search depth;
- equal-time paired-game Elo.

Incremental accumulators require differential tests against full recomputation across long random legal games, including promotions, captures, castling, en-passant and large numbers of king moves.

## Python-track evidence

The parallel Python/Chessathon project may provide useful experimental evidence, training data, model shapes, inference-cost measurements, ablations or adversarial positions. Those results inform prioritisation but never enter Rust production solely by transfer.

A Python result becomes actionable when its experiment is sufficiently isolated and reproducible, ideally including:

- frozen predecessor;
- exact evaluator delta;
- diverse paired opening corpus;
- W/D/L and uncertainty;
- NPS / average completed depth;
- evaluator/inference cost.

Rust still reimplements and requalifies the idea independently.

## Experiment discipline

Every evaluator experiment follows:

```text
frozen accepted predecessor
        ↓
one isolated hypothesis
        ↓
correctness / invariants
        ↓
cost measurements
        ↓
diverse colour-reversed paired games
        ↓
accept or reject
```

Deterministic same-start repetitions are not independent strength evidence.

## Interaction with search

Evaluation and selective search should be co-designed but independently measurable.

- PVS and aspiration are mostly evaluation-agnostic.
- Null-move pruning can begin conservatively with the current evaluator but should be requalified after major evaluation changes.
- Futility pruning, late-move pruning and evaluation margins should wait for a more meaningful static evaluator before aggressive tuning.
- Learned policy/uncertainty must not become a correctness dependency.

## Exit criteria for the classical evaluator phase

The classical positional evaluator is strong enough to serve as the M5 control when:

1. accepted terms have independent evidence or a documented combined qualification;
2. evaluator cost is measured and small relative to total search time;
3. no routine allocation is added to search;
4. deterministic search and make/unmake invariants remain green;
5. the current engine has been externally recalibrated after the major M4 search/evaluation gains.

The purpose is not to perfect handcrafted evaluation forever. It is to establish a strong, cheap and inspectable control against which learned evaluation must earn its place.
