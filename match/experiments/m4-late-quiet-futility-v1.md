# M4 late-quiet futility v1

## Decision

**Accepted for production.**

This experiment adds conservative late-quiet futility pruning on top of the accepted RFP + adaptive LMR v3 production search. The policy was frozen before screening and was not retuned between the 100-game screen and the fresh-seed 200-game acceptance.

## Frozen policy

A move may be skipped only when all of the following hold:

- internal null-window/scout node;
- nominal depth at most 2;
- the position is not in check;
- mate-band alpha/beta values are excluded;
- the side to move has non-pawn material, matching the accepted RFP safety gate;
- at least four moves have already been searched at the node;
- the move is an ordinary quiet move, not a capture or promotion;
- the move is not one of the two protected killers;
- the move does not give check;
- `static_eval + 180 * depth <= alpha`.

The static evaluation is shared with accepted reverse-futility pruning wherever the two mechanisms overlap, avoiding a second evaluator call at the same node.

The existing repetition, 50-move, insufficient-material, checkmate/stalemate, TT, stop-control, PVS, killer and adaptive-LMR semantics are otherwise unchanged.

## Correctness gates

Before both match stages the candidate passed:

- `cargo fmt --all -- --check`;
- strict workspace Clippy with `-D warnings`;
- `chess-search` tests;
- strategic draw tests, including winning-side repetition avoidance, losing-side repetition seeking and stalemate handling;
- `chess-eval` tests;
- `chess-core` tests/perft/reversible and Zobrist checks;
- `chess-engine` tests;
- `chess-uci` tests.

## 100-game screen

Reference: accepted LMR v3 production at `1be30731607d0f1a609a17e469aff78ee091d24e`.

Protocol:

- Fastchess 1.8.2-alpha;
- frozen `m3-uho-lichess-100-v1.epd` opening suite;
- opening SHA-256 `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`;
- `1+0.01`;
- concurrency 1;
- Hash 32 MiB each;
- paired colour reversal;
- no ponder, tablebases or evaluation adjudication;
- max 300 moves;
- seed `20260930`.

Result:

- 33 wins / 47 draws / 20 losses;
- 56.5%;
- Elo `+45.42 +/- 52.06`;
- nElo `+60.56 +/- 68.10`;
- LOS 95.93%;
- pentanomial `[3, 9, 15, 18, 5]`.

Candidate binary SHA-256: `4534b573f488d460e18dfb154a32abc1303b4f48377bb21c8a70dce81323c624`.
Reference binary SHA-256: `8c831744ea67a57bf14fa0a0c3f1c3989caad9a824cfc4a657f7cc43ecf44540`.
Screen artifact ID: `10015164856`.
Screen artifact ZIP SHA-256: `350ff3ca496058b127c155fdeef72640b4f4f5b960f02d31ec3bd4074a7f8bd4`.

## Fresh-seed 200-game acceptance

The identical frozen policy was rerun with seed `20261002`; no gate, depth, margin or move-order rule changed after the screen.

Result:

- **77 wins / 73 draws / 50 losses**;
- **56.75%**;
- **Elo `+47.19 +/- 35.79`**;
- **nElo `+64.52 +/- 48.15`**;
- **LOS 99.57%**;
- pentanomial **`[4, 19, 35, 30, 12]`**;
- WL/DD ratio 1.92.

Candidate binary SHA-256: `4534b573f488d460e18dfb154a32abc1303b4f48377bb21c8a70dce81323c624`.
Reference binary SHA-256: `8c831744ea67a57bf14fa0a0c3f1c3989caad9a824cfc4a657f7cc43ecf44540`.
Fastchess binary SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`.
Acceptance workflow run: `34113409742`.
Acceptance job: `101714575344`.
Acceptance artifact ID: `10015522071`.
Acceptance artifact ZIP SHA-256: `1e0019bfc5bbbea6368ace87459e1d426818f84fb7f2626f78fee069d21e6b3f`.
Acceptance PGN SHA-256: `7a1afc6ff09b7262f2e1786cf2f83ae96fa9cd07ff05ee33f8e290346612d865`.

The retained, formatted `crates/chess-search/src/lib.rs` from the acceptance artifact has SHA-256:

`cfe561488407366ace7ade6319651d518d788af56442ed93a87919d1cccd1c38`

Production promotion must use exactly that source.

## Interpretation

Unlike the rejected generic late-move-pruning experiment, this policy is gated by both move lateness and a conservative static fail-low condition. It complements RFP and LMR rather than merely duplicating them: RFP cuts clearly high static scout nodes, LMR reduces late quiets and verifies alpha raises, while this mechanism skips only very late shallow quiets whose static ceiling is well below alpha.

The gain reproduced almost exactly from the screen to the larger fresh-seed acceptance, so this is substantially stronger evidence than the many M4 candidates whose initial signal collapsed at acceptance scale.
