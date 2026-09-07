# M4 RFP early legal-move probe v1

## Decision

**ACCEPTED.** Promote the exact qualified core/search sources over production `main@ee22e91f5b3a391bbde23f054ac4c6278fecb32a`.

This is a semantics-neutral hot-path optimization around the already accepted reverse-futility-pruning (RFP) policy. It does not intentionally alter evaluation, move ordering, draw policy, TT semantics, LMR, late-quiet futility, or the RFP pruning condition.

## Change

Before this experiment, recursive search constructed and legality-filtered the complete legal move list before testing RFP, even when an eligible scout node would immediately be discarded by the static cutoff.

The candidate adds `has_legal_move_mut`, which follows the ordinary pseudo-legal move order and exact reversible make/unmake legality check, but returns after finding the first legal move. On RFP-eligible non-check nodes search now:

1. proves the position is nonterminal with the early-exit probe;
2. evaluates the existing RFP condition;
3. avoids full legal-list construction if RFP cuts;
4. otherwise runs the unchanged full generator, MovePicker and recursive search.

In-check nodes retain the ordinary terminal/full-move path. The probe is covered by restoration/equivalence tests including ordinary positions, quiet-only positions, stalemate, checkmate and a complex middlegame.

## Frozen environment

- Reference: `ee22e91f5b3a391bbde23f054ac4c6278fecb32a`
- Fastchess: 1.8.2-alpha
- Time control: `1+0.01`
- Concurrency: 1
- Hash: 32 MiB per engine
- Paired colour reversal: yes
- Ponder/tablebases/evaluation adjudication: disabled
- Maximum game length: 300 moves
- Opening suite SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`
- Fastchess binary SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`

## 100-game screen

Seed `20261004`.

- W/D/L: **38 / 39 / 23**
- Score: **57.50%**
- Elo: **+52.51 ±44.59**
- nElo: **+81.89 ±68.10**
- LOS: **99.08%**
- Ptnml: **`[0,10,20,15,5]`**
- Candidate binary SHA-256: `4ed628eaada801f2230effc3e158fbc95b67157863aaadb19693b671c64a5530`
- Reference binary SHA-256: `4534b573f488d460e18dfb154a32abc1303b4f48377bb21c8a70dce81323c624`
- Workflow run: `34114957217`
- Artifact ID: `10015990192`
- Artifact ZIP SHA-256: `a7d6f2ef61a2480bf5eaa6efcf2cc8030fe44866b98b19b345e5d3855437ded4`

## Fresh-seed 200-game acceptance

Seed `20261006`. Exact source hashes from the successful screen were required before build and play.

- W/D/L: **65 / 89 / 46**
- Score: **54.75%**
- Elo: **+33.11 ±32.21**
- nElo: **+49.93 ±48.15**
- LOS: **97.89%**
- Ptnml: **`[1,23,42,24,10]`**
- Candidate binary SHA-256: `4ed628eaada801f2230effc3e158fbc95b67157863aaadb19693b671c64a5530`
- Reference binary SHA-256: `4534b573f488d460e18dfb154a32abc1303b4f48377bb21c8a70dce81323c624`
- Workflow run: `34115536290`
- Artifact ID: `10016351213`
- Artifact ZIP SHA-256: `6ab70914fe566711182d5474f5c26bb7047964e109ca3b06994c02cf4e246bc9`

The candidate binary identity was unchanged between screen and acceptance.

## Exact retained production sources

- `crates/chess-core/src/movegen.rs`: `7eb040275a6dec56e95effff13880d0353afe9adee49806956bfbc6d6b5c1da0`
- `crates/chess-core/src/lib.rs`: `e07ad84047557eb6444e5f4460c6195443c959fbd1b0303f639016237a1a36a5`
- `crates/chess-search/src/lib.rs`: `5e6369536ce2b2d6e123e0ed400224e9ce21aaae5492f8caba9cdc3139919557`

## Correctness / benchmark gate

Both qualification stages passed strict formatting/Clippy and the relevant workspace/search/draw tests. The strategic repetition/stalemate suite remained green.

The deterministic benchmark remained exactly:

- suite: `reference-search-v8`
- signature: **`0x4c3bbe8701fbbb68`**

This unchanged fixed-depth signature is important evidence that the measured equal-time gain comes from avoiding wasted hot-path work rather than deliberately changing chess semantics.
