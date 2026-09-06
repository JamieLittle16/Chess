# M4 staged MovePicker v1 screening

This experiment compares the staged allocation-free MovePicker candidate against the accepted bounded
qsearch v1 baseline at main commit `429008867c0eb40b883dc15124479c34e0df5074`.

The deterministic `reference-search-v4` review keeps all five qsearch-v1 benchmark scores and best
moves unchanged while reducing Kiwipete depth-2 counted work from 3,066 to 1,023 nodes. That is strong
search-shape evidence but not a strength result: the picker also performs lazy tactical scoring, so
only equal-wall-clock games can determine whether the reduced tree outweighs ordering overhead.

Protocol: `match/protocols/m4-picker-v1-screening.json`.

## Result

The retained screening built candidate `aa8d4a8ce6eb97efc0e3f6b583e0e455b119bdd8` against accepted
qsearch v1 `429008867c0eb40b883dc15124479c34e0df5074`, then ran 100 games at `1+0.01`,
concurrency 1, from the frozen opening corpus with paired colour reversal.

- candidate executable SHA-256: `f898b5723315e04a6326b67f37ce9afbbed2c22106c723cc9fe125307e529738`;
- qsearch reference executable SHA-256: `50cd8a5755ac2681ebdf96a73480bdb114be99cc4a6d31bc46b95b4dbc8c2e74`;
- Fastchess executable SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`;
- opening corpus SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`;
- games: 100;
- wins / losses / draws: **28 / 7 / 65**;
- score: **60.5 / 100 (60.50%)**;
- pentanomial: `[0, 4, 25, 17, 4]`;
- Fastchess Elo estimate: **+74.06 ± 37.99**;
- nElo estimate: **+137.44 ± 68.10**;
- LOS: **100.00%**;
- retained Actions artifact ID: `9992411493`;
- retained artifact ZIP SHA-256: `bf7a75a146f383e6e3931f651e0f9e2252a9d0edf8b95e2e91e185dabb42041c`.

Fastchess printed a `DrawRatio` statistic of 50.00%; the raw game record above is authoritative for
W/L/D and contains 65 drawn games. No crash or time-forfeit was observed in the completed match.

This is a short-control development screening, not a universal Elo claim. Within the frozen protocol,
the staged picker converts its deterministic search-shape improvement into a clear positive strength
result, so it is accepted as the next M4 baseline subject to the ordinary correctness/CI gate.
