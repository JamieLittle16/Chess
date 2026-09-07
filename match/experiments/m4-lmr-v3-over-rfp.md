# M4 adaptive verified LMR v3 over RFP

Status: **accepted for production**.

## Hypothesis

Earlier LMR policies used a fixed one-ply reduction and did not survive clean acceptance. V3 tests whether a depth- and move-index-dependent schedule can reduce genuinely late ordinary quiets more aggressively at deep nodes while preserving tactical/search correctness through mandatory full-depth verification.

## Frozen policy

- recursive negamax only; root search unchanged;
- first/TT move is never reduced;
- captures and promotions are never reduced;
- killer moves are never reduced;
- nodes in check are never reduced;
- checking moves are never reduced;
- R1 at depth >= 3 for fifth and later moves;
- R2 at depth >= 6 for ninth and later moves;
- R3 at depth >= 9 for thirteenth and later moves;
- if a reduced null-window probe raises alpha, immediately repeat the probe at full depth;
- ordinary PVS full-window verification still applies to a full-depth in-window alpha improvement;
- evaluator, qsearch, TT, RFP and draw rules are unchanged.

## Correctness gates

Before both match stages the candidate passed formatting, strict Clippy, chess-search/core/engine/UCI tests and the strategic draw regression suite. The exact screened search source was retained and the acceptance branch was required to materialize byte-identical source before the 200-game match.

Exact accepted `crates/chess-search/src/lib.rs` SHA-256:

`c360b892f7c5686bc977c5ab56aa85920fd844fe7043836ae305caf483a5af82`

## 100-game screen

Against accepted RFP production `44c1e16d3713cdca1ff1bd71f7596ef3b5804037` under the frozen paired `1+0.01`, Hash=32, concurrency=1 UHO protocol:

- 36 wins / 41 draws / 23 losses;
- score 56.5%;
- Elo +45.42 +/-48.12;
- LOS 97.02%;
- Ptnml `[1,11,17,16,5]`.

Screen artifact ID `10010750715`; ZIP SHA-256 `7e71d15050e5454d81b4f6f72368acd23d915f0f9cd2c03531dd82baadb28f39`.

## Clean 200-game acceptance

GitHub Actions run `34107119861`, fresh seed `20260918`, same frozen opening/tool protocol:

- **69 wins / 84 draws / 47 losses**;
- **score 55.5%**;
- **Elo +38.37 +/-36.14**;
- **nElo +51.73 +/-48.15**;
- **LOS 98.24%**;
- **Ptnml `[5,19,37,27,12]`**.

Identities:

- candidate executable SHA-256 `8c831744ea67a57bf14fa0a0c3f1c3989caad9a824cfc4a657f7cc43ecf44540`;
- RFP reference executable SHA-256 `3f2f321508da8ce4ea7151fb6b9c568041843a2f225a21909fd347dbb99333a5`;
- Fastchess binary SHA-256 `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`;
- opening-suite SHA-256 `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`;
- acceptance artifact ID `10013094655`;
- artifact ZIP SHA-256 `74b803e47be0afb9aebbb8423b6be33844ae2197e14023a8bfd6933e6b234b10`.

## Decision

Accept LMR v3. Unlike v2, the stronger screen survived exact-source 200-game acceptance with high LOS. Future search/evaluation candidates must be measured marginally against the LMR production stack once it lands; do not add this Elo arithmetically to independent RFP-baseline screens.
