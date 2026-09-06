# M4 PVS v1 screening

Status: **accepted**

Date: 2026-09-06

## Purpose

Measure principal variation search as an isolated search-window optimization on top of the accepted staged MovePicker baseline.

## Candidate

- screened revision: `88db9a21e3866fef1bdfe11575da65bfbbc6a3f4`
- candidate executable SHA-256: `9f413d1c141cb252568418913dda04e53f9f7abb9dcb176f031022096eac7da9`

The candidate searches the first move at a node with the full alpha-beta window. Later moves receive a null-window probe and are re-searched at the full window only when they genuinely improve alpha inside beta. No move is pruned or depth-reduced.

## Reference

- accepted staged MovePicker baseline: `48bfebedb9aee3017ae8b3c5e56eb93352bd874f`
- reference executable SHA-256: `f898b5723315e04a6326b67f37ce9afbbed2c22106c723cc9fe125307e529738`

## Protocol

- protocol: `m4-pvs-v1-screening`
- 100 games / 50 colour-reversed pairs
- time control: `1+0.01`
- concurrency: 1
- seed: `20260906`
- maximum 300 moves
- no ponder
- no tablebases
- no evaluation-based adjudication
- opening suite: `m3-uho-lichess-100-v1`
- opening SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`

Fastchess:

- version: `1.8.2 alpha`, build `20260726-f618e34`
- executable SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`

## Result

```text
Games:      100
Wins:        19
Draws:       74
Losses:       7
Points:    56.0 / 100 (56.00%)

Elo:       +41.89 +/- 30.29
nElo:      +95.35 +/- 68.10
LOS:        99.70%
DrawRatio:  62.00%
Ptnml:      [0, 4, 31, 14, 1]
```

The equal-time result strongly favours PVS.

## Deterministic review

All five reviewed scores and best moves remain unchanged versus `reference-search-v4`.

- startpos: 615 -> 615 nodes
- Kiwipete: 1,023 -> 1,023 nodes
- mate-net: 68 -> 69 nodes
- en-passant: 62 -> 62 nodes
- promotion: 37 -> 37 nodes

The deterministic baseline therefore advances to `reference-search-v5`, signature `0xcf75635bf2de5791`.

The almost-neutral shallow benchmark is not a contradiction: PVS is a depth-sensitive efficiency mechanism, and the equal-time games exercise substantially deeper iterative searches. This result is also why the project keeps wall-clock Elo qualification separate from the small deterministic CI signature.

## Retained evidence

GitHub Actions run: `34045601296` (`M4 PVS screening`).

Artifact:

- name: `m4-pvs-vs-picker-88db9a21e3866fef1bdfe11575da65bfbbc6a3f4`
- artifact ID: `9993046505`
- artifact ZIP SHA-256: `574ac869da42c07be2195aa99bcf08fdd100d0ec28ed2d6d73ff06bbe24047c5`
- contents: manifest, complete PGN, raw Fastchess output, UCI log

## Decision

Accept PVS v1 as the next production search baseline. Aspiration windows remain a separate experiment so their marginal effect can be measured independently.
