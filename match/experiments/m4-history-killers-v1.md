# M4 killer + history quiet ordering v1

Status: **rejected**

Date: 2026-09-06

## Hypothesis

The accepted staged MovePicker is strong on tactical ordering but still searches untouched quiet moves largely in generator order. Alpha-beta cutoffs may provide reusable information about which quiet moves are worth trying early.

The tested ordering was:

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

## Runtime design tested

- two killer slots per search ply in a fixed `Searcher` array;
- a compact side/from/to history table owned by `Searcher`;
- history bonuses recorded only for quiet beta-cutoff moves and scaled with nominal depth;
- bounded-gravity history updates;
- heuristics persisted through iterative deepening and engine moves and reset on `ucinewgame`;
- no heap allocation or global move sort in recursive search;
- qsearch retained its accepted v1 ordering;
- no counter-move heuristic, aspiration, null-move pruning, LMR or other pruning/reduction bundled.

The history table used 2 × 64 × 64 `i32` scores (32 KiB).

## Correctness and deterministic evidence

Formatting, strict Clippy and all focused `chess-search` tests passed. The ordinary `reference-search-v5` signature remained unchanged, including all reviewed scores, moves and shallow node counts.

This is therefore a strength/performance rejection, not a correctness rejection.

## Equal-time screen

Candidate revision used by the screening workflow: `33f5ed9a3a53c0162e4b900588b3f1a3a5a628d8`.

Reference: accepted PVS baseline `339dcec0bf949c968f8ce5401c1f776108d2a691`.

Protocol:

- 100 games / 50 colour-reversed pairs;
- `1+0.01`;
- concurrency 1;
- seed `20260906`;
- frozen `m3-uho-lichess-100-v1` corpus;
- no ponder, tablebases or evaluation adjudication.

Result:

```text
Games:       100
Wins:         17
Draws:        67
Losses:       16
Points:     50.5 / 100 (50.50%)

Elo:        +3.47 +/- 36.80
nElo:       +6.45 +/- 68.10
LOS:        57.37%
DrawRatio:  54.00%
Ptnml:      [1, 10, 27, 11, 1]
```

Executable/tool identities:

- candidate SHA-256: `35cfe3ae3b12e16b014fb05d7abdb6004ea1ee23f4f3756c768835ea036258c5`;
- reference SHA-256: `9f413d1c141cb252568418913dda04e53f9f7abb9dcb176f031022096eac7da9`;
- Fastchess SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`;
- opening SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`.

Retained evidence:

- Actions run `34047097033`;
- artifact `m4-history-vs-pvs-33f5ed9a3a53c0162e4b900588b3f1a3a5a628d8`;
- artifact ID `9993483484`;
- artifact ZIP SHA-256 `edda92b268e1f183facd6ae876c3ec4516d78b3570b151fac7971c3d79dabf85`.

## Decision

Reject this combined v1 policy. The observed +3.47 Elo is statistically indistinguishable from zero and does not justify its additional per-node quiet-selection work.

This does **not** establish that killer/history ideas are intrinsically weak. The v1 implementation scans the remaining quiet set repeatedly to select history maxima, and all tactical moves still precede the killer stages. A future lower-overhead formulation, selective top-history stage, history maluses, or better tactical/quiet partition may be tested as a new experiment, but none inherits acceptance from this result.

Counter-moves should not be stacked onto this rejected baseline merely to rescue it. The next production experiment proceeds independently from accepted PVS.
