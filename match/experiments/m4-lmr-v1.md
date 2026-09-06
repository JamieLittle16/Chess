# M4 late-move reductions v1

Status: **candidate / not yet accepted**

## Hypothesis

Accepted PVS already makes late moves cheaper when they fail low. We can go further by reducing the nominal depth of sufficiently late quiet moves that are neither evasions nor checks, while requiring full-depth verification whenever a reduced search threatens to improve alpha.

## Conservative v1 policy

At a non-check node:

- first move is always full depth;
- tactical moves (captures/promotions) are never reduced;
- checking moves are never reduced;
- only move index 4 and later is eligible;
- only nominal depth 3 and deeper is eligible;
- eligible moves receive a one-ply reduction on their initial null-window probe;
- if the reduced probe raises alpha, repeat the null-window probe at full depth;
- only a full-depth alpha-raising result may trigger the ordinary PVS full-window re-search;
- no reduced result is stored as a completed node score by itself.

This deliberately leaves a large amount of possible LMR strength on the table in exchange for an easy-to-audit first baseline.

## Runtime constraints

- no heap allocation;
- no move sorting;
- no chess-core state changes;
- qsearch is unchanged;
- draw/TT/cancellation semantics remain unchanged;
- the checking-move guard is computed from the made child position, so v1 pays for an attack query rather than adding an unsafe cheap approximation prematurely.

## Evidence plan

1. formatting, strict Clippy, debug/release tests;
2. review deterministic search-shape drift case-by-case;
3. if behavior remains sound, run 100 paired games at `1+0.01` against accepted PVS `339dcec0bf949c968f8ce5401c1f776108d2a691` using the frozen 100-position opening suite;
4. accept only with positive equal-time evidence.

If v1 wins, later LMR work may tune reduction depth by depth/move index and combine history/policy signals. Those are separate experiments, not part of v1.
