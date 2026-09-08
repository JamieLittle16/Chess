# V14 root-qsearch quiet slider checks A

Status: **live experiment**

Hypothesis: V13's tactical qsearch is intentionally restricted to captures, en-passant and promotions.
That can hide a quiet long-range checking reply exactly at the normal-search horizon.  The first rated
V13 game provides a concrete instance: after f2-f3, ...Qc5+ is a quiet queen check enabled by the newly
opened diagonal.

Candidate A retains exact V13 qsearch after the first qsearch ply.  At `qply == 0` only, it adds legal
quiet bishop/rook/queen checks to the existing tactical set.  It does not add recursively generated
quiet checks, alter evaluation, change legality, prune moves, or modify normal search.

The first implementation deliberately uses the qualified full legal generator plus an exact
make/check/unmake oracle.  This is expected to be more expensive than a dedicated direct quiet-check
generator.  If the candidate has positive chess evidence, runtime optimization is a separate,
semantics-preserving follow-up rather than weakening the hypothesis before measuring it.

Primary diagnostic: the verified rated-game position in `match/regressions/v14-rated-game-1.json`.
Acceptance still requires broad probe and paired games; fixing that position alone is not sufficient.
