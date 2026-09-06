# Strength baselines

Strength claims in this project are experimental results, not inferred ratings. Every entry below names the engine revision, opponent, resource protocol, opening corpus and retained evidence needed to interpret it.

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

## How this baseline is used

M3 remains the frozen control group. M4 changes should first play paired games against the exact M3 reference under the same machine, opening corpus and resource protocol. Only changes which improve strength with acceptable performance/correctness trade-offs should be retained.

External Stockfish calibration is useful periodically to show where the whole engine is moving, but it is too noisy and expensive to replace candidate-vs-reference testing for every small search change.
