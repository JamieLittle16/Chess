# M5 High-Ceiling Strength Plan

The current protocol calibration remains far below the long-term ~2800 target. M5 therefore prioritizes changes with plausible triple-digit Elo ceilings rather than treating a sequence of small independent heuristics as the main route.

## Priority 1: evaluator information per search node

The jointly fitted classical v2 CP residual is the first high-ceiling candidate. Its initial equal-time screen was positive despite materially lower nodes searched per move than the accepted classical evaluator. The first question is therefore not whether to retune its weights, but whether the underlying positional information is strong at equal search effort.

Sequence:

1. Run the frozen 25k-node equal-node isolation.
2. If materially positive, profile and reduce evaluator cost without changing the frozen score function.
3. Candidate optimizations should be semantics-preserving and separately benchmarked: avoid duplicate piece scans, reuse occupancy/pawn attack information, cache pawn-only structure, fuse attack generation where possible, and consider incremental/cached state only after simpler wins are exhausted.
4. Retest optimized source at equal time against the strongest current `main`.
5. Only after the cost/benefit shape is understood should we expand the feature set or retrain.

## Priority 2: coherent search-generation upgrade

If evaluator information per node is not a large signal, the next large search experiment should be a coordinated search stack rather than isolated old heuristics: cheap history-driven quiet ordering, history-sensitive LMR, SEE used for qsearch pruning rather than the rejected capture-ordering policy, and qsearch selectivity v2. Components should still have correctness invariants, but the hypothesis is that they create value together by improving move ordering and allowing better selective search.

## Priority 3: learned evaluation

NNUE remains a major route, but the first residual NNUE experiments demonstrated that lower static teacher error does not automatically imply stronger search. Future learned-eval work must optimize search-facing targets, inference cost, and incremental update architecture together. Do not treat validation MSE as the acceptance metric.

## Rules

- Equal-time Elo remains the production acceptance metric.
- Equal-node tests are diagnostic tools for separating chess quality from runtime cost.
- No discarded result should be revived unchanged.
- Exact draw semantics and rule correctness remain non-negotiable.
- Small proven hot-path improvements are worth keeping, but they are supporting work rather than the strategic strength plan.
