# M4 PVS v1 screening

This experiment compares principal variation search against the accepted staged MovePicker baseline at
commit `48bfebedb9aee3017ae8b3c5e56eb93352bd874f`.

PVS changes search windows only. The first move at a node receives the existing full window; later
moves receive a one-point probe around alpha and are re-searched at the full window only when the
probe demonstrates a genuine alpha improvement. No move is discarded, reduced or otherwise pruned.

## Pre-match evidence

Formatting and Clippy pass, and the focused `chess-search` tests passed during integration.

Against accepted `reference-search-v4`, all five reviewed scores and best moves are unchanged. Search
work is almost identical in the deliberately shallow deterministic suite:

- startpos depth 3: 615 -> 615 nodes;
- Kiwipete depth 2: 1,023 -> 1,023 nodes;
- mate-net depth 2: 68 -> 69 nodes;
- en-passant depth 3: 62 -> 62 nodes;
- promotion depth 2: 37 -> 37 nodes.

This does not provide deterministic evidence for accepting PVS. It also does not show the material
regression seen in rejected SEE ordering v1. Because PVS is expected to matter more at deeper timed
iterations than in this small fixed-depth suite, one paired equal-wall-clock screen is justified.

Protocol: `match/protocols/m4-pvs-v1-screening.json`.

Acceptance requires a positive equal-time result sufficient to justify the extra probes/re-searches.
A flat or negative result rejects this PVS implementation rather than retaining it because PVS is a
conventional alpha-beta technique.
