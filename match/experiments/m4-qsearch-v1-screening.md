# M4 qsearch v1 screening

This experiment compares the bounded M4 quiescence candidate against the frozen M3 control at
`5185f2c8de64b78ff84df12067d88d9f43ed3cb0`.

The screening exists because deterministic benchmark stability is not a strength result. The M4
candidate preserves all five reviewed benchmark scores and best moves, but quiescence changes search
work substantially, especially in Kiwipete. The acceptance question is therefore whether better
tactical stabilization outweighs reduced main-search throughput at equal wall-clock.

Protocol: `match/protocols/m4-qsearch-v1-screening.json`.

## Result

The retained screening ran on candidate `77b88f616b3f572c3ff85cecfcb340feb9b1c36a` against the
frozen M3 reference using one concurrent game and `1+0.01` wall-clock chess across 100 games from the
frozen opening corpus with paired colour reversal.

- candidate executable SHA-256: `50cd8a5755ac2681ebdf96a73480bdb114be99cc4a6d31bc46b95b4dbc8c2e74`;
- M3 reference executable SHA-256: `de16793cf8d09f2f5dee7379e5294a1bb0a45b605dd045fca2a870faa5428ba0`;
- Fastchess executable SHA-256: `3d0a8f3c8b837a96366ac838f3ddf6fe87b813abb4ad2852284c0ce409132566`;
- opening corpus SHA-256: `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`;
- games: 100;
- wins / losses / draws: **68 / 1 / 31**;
- score: **83.5 / 100 (83.50%)**;
- pentanomial: `[0, 0, 5, 23, 22]`;
- Fastchess Elo estimate: **+281.68 ± 58.17**;
- nElo estimate: **+505.33 ± 68.10**;
- LOS: **100.00%**;
- draw ratio: 31%;
- retained Actions artifact ID: `9992177943`;
- retained artifact ZIP SHA-256 reported by Actions: `93b8ab2de4b98f1fc3c649977faebbc6ebf4c863332c85613f6e2155f2a9dc4f`.

The result is a short-control development screening, not a universal Elo claim. Within this frozen
protocol it is nevertheless decisive evidence that bounded qsearch more than repays its additional
leaf work. Qsearch v1 is therefore accepted as the next M4 strength baseline, subject to the normal
correctness/CI gate.

## Search-shape note

The deterministic `reference-search-v3` suite keeps the same five scores and best moves as v2 while
recording the changed work distribution. The largest observed increase is Kiwipete depth 2, from 182
M3 nodes to 3,066 qsearch-counted nodes. That cost remains an explicit optimization target for staged
tactical ordering and SEE; the positive paired-game result does not make the extra work free.
