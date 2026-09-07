# M4 mutation-free legality filtering v1

Decision: **ACCEPTED**

This experiment replaces make/unmake-based king-safety filtering of already-generated pseudo-legal moves with a mutation-free post-candidate attack test. Pseudo move generation and move order are unchanged.

## Baseline

Reference production:

`70484195439dc79d3610e36bcac88feb801a7721`

Deterministic benchmark:

- suite: `reference-search-v8`
- signature: `0x4c3bbe8701fbbb68`

Match protocol family:

- Fastchess 1.8.2-alpha
- `1+0.01`
- concurrency 1
- Hash=32 MiB for both engines
- frozen `m3-uho-lichess-100-v1` opening suite
- opening SHA-256 `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`
- paired colour reversal
- no ponder
- no tablebases
- no evaluation adjudication
- maximum 300 moves

## Candidate

For each structurally valid generated candidate the legality filter computes:

- post-move occupancy;
- the resulting king square;
- captured-piece removal, including the true en-passant capture square;
- castling rook displacement;
- surviving enemy piece masks;
- final pawn/knight/king/slider attacks on the resulting king square.

This avoids updating and restoring move clocks, castling rights, en-passant state, Zobrist state and the complete reversible `Position` solely to answer whether a candidate leaves its own king attacked.

Exact accepted `crates/chess-core/src/movegen.rs` SHA-256:

`6cb728d12e983a1815056e8faba12ca1bd26f79d8fdfbf13feb0fba56c69863d`

## Correctness gates

Before games, the candidate passed:

- ordered legal-move differential comparison against the old make/unmake oracle on special FENs;
- explicit pin, castling, promotion and en-passant discovered-attack cases;
- a 96-ply deterministic differential playout;
- the existing perft suite;
- strict formatting and Clippy;
- all workspace tests;
- strategic repetition/stalemate regressions;
- exact unchanged `reference-search-v8` signature `0x4c3bbe8701fbbb68`.

The old make/unmake legality path remains represented in the differential test as a correctness oracle.

## 100-game screen

Seed: `20261011`

Result:

- 38 wins
- 40 draws
- 22 losses
- score 58.00%
- relative Elo **+56.07 +/- 51.22**
- LOS **98.61%**

Screen candidate executable SHA-256:

`0490eeea7cb31209f820af4f9409c7df8abc6423930f904f56f578979573d6e2`

Reference executable SHA-256:

`4ed628eaada801f2230effc3e158fbc95b67157863aaadb19693b671c64a5530`

Evidence:

- Actions run `34127293354`
- artifact ID `10020750691`
- artifact ZIP SHA-256 `9ae213f0791dfde0d962fb7ec8cab350f96793f53d2ecaca9874cd7816714e46`

## Fresh-seed 200-game acceptance

Seed: `20261013`

The exact screened source hash was verified before build and match.

Result:

- 79 wins
- 81 draws
- 40 losses
- score **59.75%**
- relative Elo **+68.63 +/- 33.66**
- LOS **100.00%**

Evidence:

- Actions run `34136520700`
- artifact ID `10024462155`
- artifact ZIP SHA-256 `f23caeaf467b02fff29969741dba947a89e0cf60b03cf8fc93ded0a7004d73cb`

The retained artifact contains the complete PGN/log/manifest evidence and the exact patched source used for acceptance.

## Interpretation

This is a semantics-neutral hot-path win. It improves full legal generation, tactical legal generation and the RFP legal-existence probe through the shared legality predicate while preserving the exact legal move set, ordering and deterministic fixed-depth search behaviour.

It is therefore accepted into production. Any contemporaneous candidate measured only against `7048419` becomes stale once this change lands and must prove marginal value over the stronger production engine before merge.
