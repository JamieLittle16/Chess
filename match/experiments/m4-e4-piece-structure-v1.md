# M4 E4 piece structure v1 — accepted

E4 adds three deliberately cheap tapered positional terms to the accepted E1 PSQT + killer baseline:

- bishop pair: `+30` MG / `+45` EG;
- rook on an open file: `+16` MG / `+12` EG;
- rook on a semi-open file: `+8` MG / `+6` EG.

The implementation is allocation-free, uses existing piece bitboards only, and performs no legal move generation. No search, time-management or draw-rule semantics change.

## Reference

Production reference for qualification:

`main@54a1075912358d206cd924878d1cbdc876a30629`

That baseline already contains the accepted two-slot killer ordering and the strategic draw regressions.

## Initial marginal screen

100 games on `m3-uho-lichess-100-v1` at `1+0.01`, concurrency 1, Hash 32 MiB, paired colour reversal:

- 31 wins / 47 draws / 22 losses;
- 54.5%;
- `+31.35 +/- 49.55` Elo;
- LOS `89.54%`.

This was promising enough to materialize the exact candidate but not sufficient for acceptance.

## Exact-source acceptance on the frozen development suite

The materialized Rust candidate was checked with rustfmt, strict Clippy, evaluator/search/core/engine tests, including the strategic repetition/stalemate suite, before its 200-game acceptance match.

Result:

- 60 wins / 95 draws / 45 losses;
- 53.75%;
- `+26.11 +/- 32.35` Elo;
- LOS `94.43%`.

Because this landed narrowly below the preferred confidence line, the threshold was not relaxed. Instead the candidate received a genuinely fresh holdout test.

## Disjoint UHO holdout

The holdout was generated reproducibly from Stockfish's pinned `UHO_Lichess_4852_v1.epd.zip` source:

- source repository: `official-stockfish/books`;
- source commit: `65815ccdbc7727cd4f6aee252ba8f67fb740e92f`;
- source archive SHA-256: `4e298f11e8acfa106babe02968f2e61582145e7874c59284690b20b9650e0e07`;
- source positions: 2,632,036;
- holdout selector seed: `Chess/m4-e4-uho-holdout-100-v1`;
- holdout positions: 100;
- every source line used by the original `m3-uho-lichess-100-v1` suite was explicitly excluded;
- holdout EPD SHA-256: `239584acc317f0b05e3c2cf9e1a4941a97081ded11f02364d1d1602840fa3b23`.

The selector and selected source-line metadata were retained with the Actions evidence, making zero source-line overlap directly auditable.

Fresh 200-game holdout result:

- **70 wins / 80 draws / 50 losses**;
- **55.0%**;
- **`+34.86 +/- 35.54` Elo**;
- **LOS `97.40%`**;
- nElo `+47.72 +/- 48.15`;
- pentanomial `[6, 17, 38, 29, 10]`.

Actions run: `34060222632`.

Evidence artifact:

- artifact ID: `9997348269`;
- artifact ZIP SHA-256: `ad5c33cbcc9cc67e6ad95534a41fa0e28861183b82cf3c77f2d91f9b23fed62a`;
- candidate executable SHA-256: `6c01235f17a2723570dd1c4ef1a52e5d6fe9500c4f7b44ef613b3671dff3df20`;
- reference executable SHA-256: `10364339a1f7b3168ec38e4be2a9282a7b67d5aeb865d94e754a3f08476a70d4`;
- Fastchess executable SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`.

## Deterministic search baseline

E4 intentionally changes evaluation and therefore search shape. The reviewed deterministic baseline advances to `reference-search-v8`:

- startpos d3: `+24`, 649 nodes, 22 TT hits, best raw 82;
- Kiwipete d2: `+17`, 1,137 nodes, 2 TT hits, best raw 3,427;
- mate-net d2: `29,999`, 72 nodes, 1 TT hit, best raw 3,446;
- en-passant d3: `+167`, 63 nodes, 7 TT hits, best raw 22,827;
- promotion d2: `+886`, 62 nodes, 2 TT hits, best raw 9.

Signature: `0x4c3b_be87_01fb_bb68`.

## Decision

**Accept E4.** The first exact-source test showed a repeatable positive trend, and a fresh disjoint holdout independently cleared the confidence threshold. Subsequent evaluator or search experiments must measure marginal value on top of this E4 baseline rather than relying on results against the older killer-only engine.
