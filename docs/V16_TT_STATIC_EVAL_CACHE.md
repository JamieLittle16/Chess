# V16 TT static-evaluation cache

Status: **candidate accepted for production integration pending ordinary CI on the materialized source**.

Base: V15 documentation anchor `8e53d63a766122f70992942eccaac22be9e5fca3`.

## Change

V15 already probes the transposition table before reverse-futility pruning, but a same-position TT hit
that cannot return a search bound may still reach the static-evaluation call used by RFP and late-quiet
futility. The V16 candidate stores that already-computed static evaluation alongside the ordinary TT
entry and reuses it on a later same-key visit.

The cache is deliberately conservative:

- no eval-only TT entries are created;
- TT bound/cutoff semantics are unchanged;
- TT depth and replacement semantics are unchanged;
- pruning margins and eligibility are unchanged;
- the existing legal-move terminal guard still runs before static-eval reuse;
- the cached value is `i16`, sufficient for ordinary non-mate static evaluations;
- same-key replacement inherits a cached static evaluation if the replacement search did not compute
  one itself.

`TtEntry` remains **24 bytes** on the pinned x86-64 toolchain, so the configured Hash budget retains
exactly the same number of entries.

## Exact-search certification

Both independent qualification runs produced the exact same deterministic production-Gestalt search
signature as V15, including best moves, scores, nodes and TT hits:

```text
startpos   depth 3  score    24  nodes  955  tt_hits 18  bestmove 0x12db
kiwipete   depth 2  score  -288  nodes 1514  tt_hits  1  bestmove 0x4328
mate       depth 2  score 29999  nodes   72  tt_hits  1  bestmove 0x0d76
en-passant depth 3  score  1193  nodes   63  tt_hits  7  bestmove 0x592b
promotion  depth 2  score  1206  nodes   68  tt_hits  4  bestmove 0x0009
signature = 0xbf26e567ca40b383
```

This is the key semantic guard: the candidate does not obtain its speedup by pruning a different tree.

## Fixed-node timing evidence

The timing harness keeps each UCI engine process alive, excludes NNUE load/startup from search timing,
clears game state between samples, and runs a deterministic five-position corpus at 250,000 nodes per
search. Each pass contains three repeats per position and alternates reference/candidate to reduce
runner drift.

First qualification:

```text
reference mean = 6831.706 ms
candidate mean = 6760.640 ms
wall-clock speedup = +1.051%
search identity = exact
```

Independent rerun:

```text
reference mean = 6794.805 ms
candidate mean = 6768.268 ms
wall-clock speedup = +0.392%
search identity = exact
```

Both measurements are positive. The effect is intentionally small: this is a low-risk hot-path saving,
not a search-strength change. Because TT capacity and explored search are identical, it can be composed
with later evaluator/search improvements rather than consuming Elo-risk budget.

## Decision

Keep the materialized source change if ordinary repository CI is green. This is a measured performance
win with no observed chess/search semantic change and no TT-capacity cost.
