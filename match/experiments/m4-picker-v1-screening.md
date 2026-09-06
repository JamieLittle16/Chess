# M4 staged MovePicker v1 screening

This experiment compares the staged allocation-free MovePicker candidate against the accepted bounded
qsearch v1 baseline at main commit `429008867c0eb40b883dc15124479c34e0df5074`.

The deterministic `reference-search-v4` review keeps all five qsearch-v1 benchmark scores and best
moves unchanged while reducing Kiwipete depth-2 counted work from 3,066 to 1,023 nodes. That is strong
search-shape evidence but not a strength result: the picker also performs lazy tactical scoring, so
only equal-wall-clock games can determine whether the reduced tree outweighs ordering overhead.

Protocol: `match/protocols/m4-picker-v1-screening.json`.

Acceptance evidence to retain:

- exact candidate and reference executable hashes;
- exact Fastchess and opening-corpus hashes;
- 100 paired games with colours reversed;
- W/D/L and pentanomial counts;
- relative Elo estimate and uncertainty;
- PGN, raw runner output and UCI log;
- any crash or time-forfeit evidence.

Status: screening re-triggered after correcting the one-shot Actions condition; engine code and the V4
deterministic signature remain frozen. The outcome will be appended only after retained evidence is
inspected.
