# M4 SEE ordering v1 screening

This experiment compares SEE-based tactical ordering against the accepted staged MovePicker baseline
at commit `48bfebedb9aee3017ae8b3c5e56eb93352bd874f`.

The candidate changes ordering only. It does not use SEE for pruning. Tactical candidates are still
selected lazily by the accepted cheap tactical score; a candidate with negative static exchange
value is deferred behind quiet moves.

## Pre-match evidence

All reviewed benchmark scores and best moves remain unchanged. The deterministic Kiwipete depth-2
work count increases from 1,023 nodes on the accepted picker to 1,092 nodes with SEE ordering
(+69 nodes, approximately +6.7%). This is mildly negative search-shape evidence, and SEE itself also
has CPU cost, so the candidate is not accepted on deterministic evidence alone.

The paired match was run because the fixed benchmark is deliberately small and SEE targets a broader
class of poisoned/losing captures. Equal-wall-clock games decide whether that broader ordering benefit
repays the local regression and SEE computation cost.

Protocol: `match/protocols/m4-see-v1-screening.json`.

## Correctness gate

The dedicated qualification job ran the search crate independently of the intentionally drifting
reference benchmark:

- formatting: pass;
- Clippy with `-D warnings`: pass;
- `cargo test -p chess-search --all-features`: **26 passed / 0 failed**;
- SEE regressions for undefended capture, poisoned capture, pinned recapturer and promotion: pass.

So the rejection below is a strength/performance decision, not a correctness failure.

## Equal-time result

Candidate source/run commit: `1ce2f5b3e64cd7fd6e7bf73cbab212e01324ec6b`.
Reference: accepted staged MovePicker at `48bfebedb9aee3017ae8b3c5e56eb93352bd874f`.

100 games at `1+0.01`, concurrency 1, frozen 100-position opening corpus, paired colour reversal:

- **12 wins / 16 losses / 72 draws**;
- **48.0 / 100 (48.00%)**;
- pentanomial `[2, 8, 32, 8, 0]`;
- Fastchess Elo estimate **-13.90 ± 33.29**;
- LOS **20.55%**.

Recorded identities:

- candidate executable SHA-256: `038936c3e9de44ee6a7a818b930fe642ded12a193b1fd719160b93210f94f453`;
- accepted picker executable SHA-256: `f898b5723315e04a6326b67f37ce9afbbed2c22106c723cc9fe125307e529738`;
- Fastchess executable SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`;
- opening corpus SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`.

Retained GitHub Actions artifact:

- name: `m4-see-vs-picker-1ce2f5b3e64cd7fd6e7bf73cbab212e01324ec6b`;
- artifact id: `9992881879`;
- artifact ZIP SHA-256: `ba2d66358f110da3d7775ea5104a86915add6b6e5f6371132fed16dadf5b997a`.

## Decision: reject SEE ordering v1

The candidate is rejected and must not advance the production search baseline.

The evidence is aligned rather than ambiguous:

1. deterministic Kiwipete work regresses by about 6.7%;
2. SEE adds non-zero computation to move selection;
3. the equal-time match is slightly negative rather than compensating for that cost.

This does **not** reject static exchange analysis as a technique. It rejects the specific policy
`TT -> SEE-non-losing tactical -> quiet -> SEE-losing tactical` in the current engine. Future isolated
experiments may still use SEE for qsearch pruning, selective thresholds, diagnostics, or opponent
fragility probes. Those experiments must start again from an accepted baseline and earn their place
independently.
