# M4 killer + history quiet ordering v1

Status: **candidate / not yet accepted**

## Hypothesis

The accepted staged MovePicker is strong on tactical ordering but still searches untouched quiet moves largely in generator order. Alpha-beta cutoffs should provide reusable information about which quiet moves are worth trying early.

This experiment adds two coupled quiet-ordering signals while preserving the accepted tactical stages:

```text
TT move
  ↓
tactical moves (existing lazy score)
  ↓
killer 1 for this ply
  ↓
killer 2 for this ply
  ↓
remaining quiets selected lazily by history
```

## Runtime design

- two killer slots per search ply in a fixed `Searcher` array;
- a compact side/from/to history table owned by `Searcher`;
- history bonuses are recorded only for quiet beta-cutoff moves and scale with nominal depth;
- bounded-gravity updates prevent unbounded score growth;
- killers/history persist through iterative-deepening iterations and real moves while the `Searcher` is reused;
- `ucinewgame` reconstructs `Engine`/`Searcher`, discarding heuristics from the previous game;
- no heap allocation or global move sort is added to recursive search;
- qsearch deliberately retains its accepted v1 ordering and does not consume quiet-history state in this experiment;
- no counter-move heuristic, aspiration, null-move pruning, LMR or other pruning/reduction is bundled.

The history table uses 2 × 64 × 64 signed scores (32 KiB with `i32` entries), small enough to remain cache-friendly while avoiding premature saturation.

## Evidence plan

1. formatting, strict Clippy and all correctness/search tests;
2. review deterministic `reference-search-v5` drift case-by-case;
3. if search shape remains correct and plausibly useful, run 100 paired equal-time games against accepted PVS baseline `339dcec0bf949c968f8ce5401c1f776108d2a691` under the frozen `1+0.01` development protocol;
4. accept only on positive strength evidence.

Counter-moves remain a later isolated experiment so their marginal value is measurable.
