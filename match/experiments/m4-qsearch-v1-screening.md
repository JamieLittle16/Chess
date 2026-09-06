# M4 qsearch v1 screening

This experiment compares the bounded M4 quiescence candidate against the frozen M3 control at
`5185f2c8de64b78ff84df12067d88d9f43ed3cb0`.

The screening exists because deterministic benchmark stability is not a strength result. The M4
candidate preserves all five `reference-search-v2` benchmark scores and best moves, but quiescence
changes search work substantially, especially in Kiwipete. The acceptance question is therefore
whether better tactical stabilization outweighs reduced main-search throughput at equal wall-clock.

Protocol: `match/protocols/m4-qsearch-v1-screening.json`.

Acceptance evidence to retain:

- exact candidate and reference executable hashes;
- exact Fastchess and opening-corpus hashes;
- 100 paired games with colors reversed;
- W/D/L and pentanomial counts;
- relative Elo estimate and uncertainty;
- PGN, raw runner output and UCI log;
- any crash or time-forfeit evidence.

This file records the experiment definition, not its outcome. The result should be added only after
the retained match artifact has been inspected.
