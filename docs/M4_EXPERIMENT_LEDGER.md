# M4 experiment decision ledger

This file is the short decision index for M4 strength work. It exists to prevent repeated infrastructure, stale-baseline Elo stacking and cargo-cult feature accumulation.

Detailed source hashes, executable hashes, opening provenance, PGNs and raw logs remain in experiment dossiers, pull requests and Actions artifacts. Numbers below are development-protocol engine results. They are not additive and are not human/FIDE ratings.

## Production baseline

As of `main@afbe9c8d9050664dbc1780b0aa1e11cae6c364b1` production contains:

- tapered geometric PSQT evaluation (E1);
- E4 bishop-pair and rook open/semi-open-file structure;
- iterative deepening and negamax alpha-beta;
- PVS/null-window probing;
- bounded direct-mapped TT with mate-distance normalization;
- bounded four-qply quiescence;
- tactical-only qsearch generation outside check and complete evasions in check;
- allocation-free staged `MovePicker`;
- TT move ordering and lazy tactical ordering;
- two quiet killer slots per ply;
- conservative reverse futility pruning v1;
- adaptive verified LMR v3;
- late-quiet futility v1;
- RFP early legal-existence probe;
- accepted mutation-free legality filtering v1;
- rule-correct repetition, 50-move and dead-material handling before TT reuse;
- strategic tests proving a winning side avoids available repetition/stalemate while a losing side accepts a draw.

Deterministic benchmark remains `reference-search-v8`, signature `0x4c3b_be87_01fb_bb68`.

The most recent external calibration was run immediately before mutation-free legality filtering landed and placed `7048419` at roughly **1830** on the project's `1+0.01` Stockfish-limited scale. See `docs/STRENGTH_BASELINES.md`.

## Accepted strength changes

| Change | Acceptance evidence | Decision |
| --- | --- | --- |
| qsearch v1 vs M3 | `+281.68 +/-58.17` Elo | accepted |
| staged MovePicker vs qsearch | `+74.06 +/-37.99` | accepted |
| PVS v1 vs staged picker | `+41.89 +/-30.29` | accepted |
| E1 tapered geometric PSQT | 62W / 26D / 12L, `+190.85 +/-64.16`, LOS 100% | accepted |
| two-slot killer ordering | 63W / 94D / 43L, `+34.86 +/-34.16`, LOS 97.83% | accepted |
| E4 bishop pair + rook-file structure, disjoint holdout | 70W / 80D / 50L, `+34.86 +/-35.54`, LOS 97.40% | accepted |
| reverse futility pruning v1 | 80W / 76D / 44L, `+63.23 +/-34.43`, LOS 99.99% | accepted |
| adaptive verified LMR v3 | 69W / 84D / 47L, `+38.37 +/-36.14`, LOS 98.24% | accepted |
| late-quiet futility v1 | 77W / 73D / 50L, `+47.19 +/-35.79`, LOS 99.57% | accepted |
| RFP early legal-existence probe | 65W / 89D / 46L, `+33.11 +/-32.21`, LOS 97.89% | accepted |
| mutation-free legality filtering v1 | 79W / 81D / 40L, `+68.63 +/-33.66`, LOS 100.00% | accepted |

These are sequential comparisons against different historical baselines. **Do not sum them to infer absolute Elo.** Interaction effects are large: several evaluator/search ideas that looked useful over weaker engines became neutral once stronger search landed.

The permanent mutation-free legality dossier is `match/experiments/m4-static-legality-v1.md`.

## Rejected or superseded hypotheses

The project deliberately keeps negative evidence so later work does not rediscover the same implementation under a new name.

| Change | Strongest relevant result | Decision / interpretation |
| --- | --- | --- |
| SEE ordering v1 | negative screen | reject ordering policy; SEE may still be useful for pruning/infrastructure |
| old full quiet-history | no proven marginal value | reject tested implementation |
| one-slot countermove | neutral | reject |
| fixed LMR v1/v2 | insufficient/non-additive | superseded by accepted adaptive verified LMR v3 |
| null-move pruning v1 | neutral | reject tested policy; reversible null substrate remains useful |
| null-move pruning v2 tested policy | weak/non-additive | reject tested policy |
| four-way clustered TT | slight loss | reject |
| raw mobility | no justified marginal gain | reject |
| pawn-safe mobility | no justified marginal gain | reject |
| E3 generic pawn structure | old signal collapsed after stronger search | reject |
| simple passed-pawn bonus | ~0 Elo | reject |
| richer passed-race v2 | old positive signal largely absorbed by LMR | reject current formulation |
| king-shelter v2 | old positive signal weakened after LMR | reject current formulation, not the concept |
| compact king danger E5 | negative | reject |
| heavy-piece king danger v3 | promising but below production threshold | retain concept, do not merge formulation |
| outpost v1 | negative | reject |
| severe minor-piece confinement | neutral | reject |
| generic endgame mop-up | tiny signal | reject |
| rook/passer coordination | tiny signal | reject |
| LMP v1 | rejected | do not repeat unchanged |
| qdelta v1 | rejected | do not repeat unchanged |
| ProbCut v1 | rejected | do not repeat unchanged |
| aspiration windows v1 | rejected | do not repeat unchanged |
| adaptive-time v1 / simple spend-more-clock policy | rejected | future time policy needs materially better signals |
| history-gated LMR v1 | rejected | do not repeat unchanged |
| inline-legality optimization | exactly neutral | distinct from accepted mutation-free legality filtering |
| periodic wall-clock polling v1 | 32W / 37D / 31L, `+3.47 +/-42.73`, LOS 56.36% | reject; correct semantics but no equal-time strength |

A rejected family can be revisited only when the hypothesis changes materially. Re-tuning the same coefficients or thresholds is not a new hypothesis.

## Current live work

### Qsearch early-exit v1 marginal re-test — PR #91

The original candidate avoided full qsearch move generation on two exits that need only legal-move existence. It first screened at `+27.85 Elo / 91.90% LOS` and then passed a fresh-seed 200-game acceptance over `7048419`:

- 71W / 78D / 51L;
- score 55.00%;
- `+34.86 +/-35.54` Elo;
- LOS 97.40%;
- exact qsearch source SHA-256 `1c7331d8240ff743ab053ce22a8ae49ac07f9c6d0b4592fc12614c3b7708c17b`.

That acceptance became stale when mutation-free legality filtering advanced production. PR #91 therefore carries the **exact same retained qsearch source** onto `afbe9c8` and runs a fresh marginal screen. The historical acceptance does not authorize a merge.

### Forced-single-evasion extension — PR #87

The candidate compiles and ordinary CI is green, but it changes the deterministic benchmark before games. In particular the Kiwipete score remains +17 while the selected root move changes. Do not weaken the benchmark gate mechanically. Inspect the changed root choice and only run games if the semantic drift is deliberately justified.

### M5 strength laboratory / learned-evaluation foundation — PR #90

This is infrastructure, not an Elo candidate. It adds reproducible full-strength Stockfish error mining, teacher-data generation with whole-game split discipline, and the incremental NNUE architecture contract. It does not change runtime engine behaviour.

## Next high-value hypotheses

The priority after current marginal tests is:

1. full-strength Stockfish error mining on retained production games;
2. search telemetry that is compiled out/disabled in tournament mode;
3. qsearch v2 infrastructure, especially correct SEE as a pruning primitive rather than universal ordering;
4. sparse incremental learned-evaluation feature deltas and a slow rebuild oracle;
5. tiny/small/medium quantized NNUE value-model ladder;
6. search retuning around an accepted learned evaluator;
7. cheap history, continuation history and correction history;
8. materially new verified null-move pruning;
9. TT-based singular extension/exclusion search;
10. learned policy only after value inference has proved its Elo-per-cost frontier.

## Decision rules

1. Correctness before Elo: formatting, strict Clippy, focused tests, reversible-state invariants and draw-strategy regressions run before candidate games.
2. Strength is measured at equal resources with paired colour reversal and pinned openings/tooling.
3. A positive result against a stale baseline does not authorize a merge. Re-test marginal value against the strongest accepted `main`.
4. Interaction matters. Independently positive evaluator/search features are stacked only after a direct marginal test when effects can overlap.
5. Genuine draws remain score `0`; do not add ad-hoc draw-aversion bonuses.
6. Temporary experiment workflows, patchers and protocols are not production architecture. Materialize exact accepted source, retain permanent evidence, remove one-shot scaffolding, then run final CI.
7. Negative experiments remain evidence. Revisit a rejected family only with a materially different hypothesis.
8. Fixed-depth benchmark drift is information, not an inconvenience. Understand it before changing the reviewed signature.
9. Equal-time Elo, not raw NPS or validation loss, decides whole-engine production strength.
