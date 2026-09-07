# Strength baselines

Strength claims in this project are experimental results, not inferred ratings. Every entry below names the engine revision, opponent, resource protocol, opening corpus and retained evidence needed to interpret it.

## Current M4 external calibration — 2026-09-07

Purpose: locate the mature pre-static-legality M4 production engine on the project's Stockfish-limited short-control scale after the accepted RFP, adaptive verified LMR v3, late-quiet futility and RFP early legal-existence probe stack.

This is a **development-protocol engine calibration**, not a human/FIDE rating claim. Stockfish `UCI_LimitStrength` is not expected to be perfectly linear, especially at this time control, so the fitted rating is an approximate locator rather than a precise absolute rating.

### Candidate

- engine source: `main@70484195439dc79d3610e36bcac88feb801a7721`;
- deterministic benchmark: `reference-search-v8`;
- benchmark signature: `0x4c3bbe8701fbbb68`;
- Threads=1;
- Hash=32 MiB.

This calibration predates the subsequently accepted mutation-free legality filter (`afbe9c8d9050664dbc1780b0aa1e11cae6c364b1`), so it should be treated as a conservative historical locator for current production rather than silently relabelled as an exact rating of the newer engine.

### Reference and protocol

Reference engine:

- Stockfish 19;
- `UCI_LimitStrength=true`;
- Threads=1;
- Hash=32 MiB.

All three rungs used:

- 100 games / 50 colour-reversed pairs;
- time control `1+0.01`;
- concurrency 1;
- frozen `m3-uho-lichess-100-v1` opening suite;
- opening SHA-256 `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`;
- no ponder;
- no tablebases;
- no evaluation adjudication;
- maximum 300 moves.

Independent seeds were used for the 1800/2000/2200 rungs.

### Results

| Stockfish `UCI_Elo` | W | D | L | Score | Relative Elo |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1800 | 36 | 13 | 51 | 42.5% | `-52.51 +/- 68.66` |
| 2000 | 24 | 8 | 68 | 28.0% | `-164.07 +/- 60.22` |
| 2200 | 16 | 11 | 73 | 21.5% | `-224.97 +/- 82.40` |

A simple fit across those three limited-strength rungs places `7048419` at approximately **1830** on this exact `1+0.01` Stockfish-limited scale. A sensible practical statement is **roughly 1800–1900, with ~1830 as a useful fitted centre**.

Do not translate this into FIDE/human Elo, and do not add experimental Elo deltas arithmetically to claim a current absolute rating.

### Retained evidence

GitHub Actions run: `34127690282` (`M4 current Stockfish calibration ladder`).

Retained rung artifacts:

- Stockfish 1800: artifact ID `10021265773`;
- Stockfish 2000: artifact ID `10021301126`;
- Stockfish 2200: artifact ID `10021305757`.

The artifacts retain the manifests, complete PGNs and raw match/UCI evidence needed to audit the calibration.

## M3 external calibration — 2026-09-06

Purpose: locate the intentionally weak material-only M3 reference engine on a real external scale before beginning M4 strength work.

This was a **short-control development calibration**, not a human/FIDE rating claim and not the long-control M3 qualification protocol.

### Engines

Candidate:

- engine: M3 classical reference engine;
- engine source baseline: `main@5185f2c8de64b78ff84df12067d88d9f43ed3cb0`;
- calibration workflow revision: `979bca9d6f17bf408ce5649e3484535b7492bfc8` (engine/search code unchanged from the M3 source baseline; branch adds only calibration protocol/workflow);
- candidate executable SHA-256: `de16793cf8d09f2f5dee7379e5294a1bb0a45b605dd045fca2a870faa5428ba0`.

Reference:

- Stockfish 19;
- `Threads=1`;
- `Hash=1` MiB;
- `UCI_LimitStrength=true`;
- `UCI_Elo=1320`;
- reference executable SHA-256: `0f83d24cc46d2c66c60f16001af5444873bc112b7d028594513426894c12da19`.

`UCI_Elo=1320` is Stockfish's own limited-strength setting. The result below therefore measures relative performance against that configured engine under this protocol; it does **not** imply a FIDE rating for our engine.

### Protocol

- protocol: `m3-calibration-stockfish1320-v1`;
- 100 games / 50 colour-reversed pairs;
- time control: `1+0.01` seconds;
- concurrency: 1;
- seed: `20260906`;
- no ponder;
- no tablebases;
- no evaluation-based resignation/draw adjudication;
- maximum 300 moves;
- opening suite: `m3-uho-lichess-100-v1`;
- opening SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`.

### Result

```text
Games:       100
Wins:         31
Draws:         9
Losses:       60
Points:     35.5 / 100 (35.50%)

Elo:       -103.73 +/- 71.87
nElo:      -106.10 +/- 68.10
LOS:          0.11%
DrawRatio:   36.00%
Ptnml:       [18, 7, 18, 0, 7]
```

The uncertainty is deliberately reported. One hundred games are enough to locate the baseline approximately, not to claim a precise rating difference.

### Retained evidence

GitHub Actions run: `34038588698` (`M3 Stockfish calibration`).

The uploaded evidence artifact was:

- name: `m3-stockfish1320-calibration-979bca9d6f17bf408ce5649e3484535b7492bfc8`;
- artifact SHA-256: `2f5e8c5424b7574b124ce6ebd2709f0ce5a029f676b7726b0cc7509997a9f600`;
- contents: match manifest, complete PGN, raw Fastchess stdout and UCI engine log.

External archives were pinned and verified before the run:

- Fastchess v1.8.2-alpha archive SHA-256: `1003f920bebe841acdab5e6d7871e93171a4586857b3ec91c21ef5777f26ff96`;
- Stockfish 19 universal archive SHA-256: `9defc0d4e55d49c65a6d042f3e571a39fcea499ade6dbe741b53b8c65e03611f`.

## How these baselines are used

M3 remains a frozen historical control group. Current strength experiments branch from the strongest accepted `main`, not from M3 and not from a stale positive experiment.

External Stockfish calibration is useful periodically to show where the whole engine is moving, but it is too noisy and expensive to replace candidate-vs-reference testing for every search/evaluation change. Recalibrate after meaningful production milestones rather than inferring absolute strength by stacking internal Elo deltas.
