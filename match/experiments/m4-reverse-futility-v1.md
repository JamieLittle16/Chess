# M4 Reverse Futility Pruning v1

Status: **accepted for production promotion**

## Mechanism

The candidate adds one conservative reverse-futility cutoff to internal negamax nodes:

- root search is unchanged;
- only null-window nodes (`beta == alpha + 1`) are eligible;
- only depths 1 through 3 are eligible;
- legal terminal detection runs first;
- no pruning while the side to move is in check;
- beta values in the mate band are excluded;
- the side to move must retain at least one knight, bishop, rook, or queen;
- prune only when `static_eval - 120 * depth >= beta`;
- qsearch, evaluator, transposition-table policy, MovePicker, killers, PVS and legal draw semantics are unchanged.

The mechanism is intentionally small: it cuts shallow positions whose static score is already well above a narrow beta bound, while keeping tactical/check, mate, terminal and low-material cases outside the gate.

## 100-game screening

Against production E4 `main@88d2843afce44921ea422da11961aaf0f8ed383f` at the frozen paired `1+0.01` protocol:

- 39 wins / 34 draws / 27 losses;
- 56.0%;
- Elo `+41.89 +/- 46.70`;
- LOS `96.30%`;
- pentanomial `[2, 7, 23, 13, 5]`.

Retained screening source SHA-256 for `crates/chess-search/src/lib.rs`:

`d04cbd5503ad4fba42b73cc3e7b7b5ee2e5893b9e847d7ac8f01884267f90523`

## Clean 200-game acceptance

The exact screened source was materialized and verified before the acceptance match. Run `34099680819` used a fresh seed (`20260911`), Hash=32 for both engines, concurrency 1, the frozen UHO suite and pinned Fastchess, with no ponder, tablebases or evaluation adjudication.

Final result:

- **80 wins / 76 draws / 44 losses**;
- **59.0%**;
- Elo **`+63.23 +/- 34.43`**;
- nElo **`+90.72 +/- 48.15`**;
- LOS **`99.99%`**;
- pentanomial **`[2, 17, 37, 31, 13]`**.

Identity evidence:

- accepted candidate binary SHA-256: `15581b550ab7b290c2845ef51edcb4d8bf1c3dc6deddf2ba78de49f0073383e2`;
- reference binary SHA-256: `6c01235f17a2723570dd1c4ef1a52e5d6fe9500c4f7b44ef613b3671dff3df20`;
- Fastchess binary SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`;
- opening suite SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`;
- acceptance artifact ID: `10010229997`;
- acceptance artifact ZIP SHA-256: `bb3fadbcfd06e8645bd439880f2b97dc3fcd0871e093fb95d6e5192c373748a2`.

## Production port

After acceptance, `main` gained the semantics-neutral M5 root-candidate analysis API. Production therefore ports the **same RFP delta** onto that newer architecture-only head instead of overwriting `chess-search/src/lib.rs` with the older accepted file wholesale.

The production port must pass strict fmt/Clippy, all workspace tests, strategic draw regressions, release tests and the frozen deterministic benchmark before merge. No RFP constant or gate may be retuned during this port.

## Decision

Accept RFP v1. The 200-game exact-source match clears the production evidence bar decisively. Future pruning mechanisms must be qualified marginally over this stronger baseline rather than adding their old independent Elo estimates.
