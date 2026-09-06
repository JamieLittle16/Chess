# M4 experiment decision ledger

This file is the short decision index for M4 strength work. It exists to prevent repeated infrastructure and cargo-cult feature stacking.

The detailed source, executable hashes, opening provenance and raw match evidence remain in the individual experiment dossiers, PRs and Actions artifacts. Numbers here are development-protocol results, not additive Elo claims and not human/FIDE ratings.

## Production baseline

As of `main@2e4dcf1e10f482783af721ad09df113a63c5ba8b`:

- tapered geometric PSQT evaluator (E1);
- accepted E4 bishop-pair and rook open/semi-open-file structure;
- bounded quiescence with tactical-only legal generation;
- staged allocation-free move picker;
- PVS/null-window probing;
- direct-mapped bounded TT with production UCI `Hash` sizing;
- two quiet killer slots per ply;
- rule-correct repetition/50-move/dead-material handling;
- strategic regressions proving a winning side avoids available repetition/stalemate while a losing side takes an available draw.

Deterministic benchmark: `reference-search-v8`, signature `0x4c3b_be87_01fb_bb68`.

## Accepted strength changes

| Change | Match result | Decision |
| --- | --- | --- |
| qsearch v1 vs M3 | +281.68 +/-58.17 Elo | accepted |
| staged MovePicker vs qsearch | +74.06 +/-37.99 Elo | accepted |
| PVS v1 vs staged picker | +41.89 +/-30.29 Elo | accepted |
| E1 tapered geometric PSQT vs material/PVS | 62W / 26D / 12L, +190.85 +/-64.16, LOS 100% | accepted |
| two-slot killer ordering vs E1 production | 63W / 94D / 43L, +34.86 +/-34.16, LOS 97.83% | accepted |
| E4 bishop-pair + rook-file structure, fresh disjoint holdout | 70W / 80D / 50L, +34.86 +/-35.54, LOS 97.40% | accepted |

These are sequential development comparisons against different historical baselines. Do not sum them to estimate an absolute rating.

E4 also had an exact-source 200-game test on the original frozen UHO development suite: 60W / 95D / 45L, +26.11 +/-32.35, LOS 94.43%. Because that landed narrowly below the preferred confidence line, the threshold was not relaxed. A second 100-position holdout was selected deterministically from the pinned 2,632,036-position Stockfish UHO Lichess source while explicitly excluding every source line used by the original suite. The independent holdout cleared the line and justified acceptance. Full provenance lives in `match/experiments/m4-e4-piece-structure-v1.md`.

## Rejected or superseded hypotheses

| Change | Strongest relevant result | Reason not in production |
| --- | --- | --- |
| SEE ordering v1 | -13.90 +/-33.29 Elo | negative equal-time screen |
| killer + full quiet-history v1 | +3.47 +/-36.80 Elo | extra quiet-selection work did not pay |
| conservative LMR v1 | +13.90 +/-44.27 Elo | positive trend, insufficient evidence; superseded by v2 policy tests |
| E3 generic pawn structure over killers | 30W / 42D / 28L, +6.95 +/-48.44, LOS 61.14% | old positive signal collapsed after stronger ordering |
| draw-safe null-move v1 | 32W / 37D / 31L, +3.47 +/-45.94, LOS 55.93% | correct architecture, no proven strength |
| one-slot countermove v1 | 29W / 43D / 28L, +3.47 +/-38.06, LOS 57.13% | no proven marginal value over killers |
| four-way clustered TT v1 | 25W / 49D / 26L, -3.47 +/-24.58, LOS 39.07% | collision reduction did not repay probing/replacement overhead at 32 MiB |
| raw E2 mobility over killers | 28W / 46D / 26L, +6.95 +/-49.42, LOS 60.93% | original pre-killer signal did not survive stronger search; attack-map cost unjustified |
| pawn-safe mobility v1 | earlier +38.37 +/-50.34, LOS 93.54% | weaker/more expensive than raw mobility and never earned acceptance |
| compact king-safety E5 v1 | 28W / 40D / 32L, -13.90 +/-49.36, LOS 28.90% | simple weighted king-zone attack counts plus shield were too crude/expensive |

A rejected implementation may still contain useful substrate. In particular, the null-transition/draw-isolation work from null-move v1 is a valid basis for a differently tuned future NMP experiment; rejection means **do not merge the tested policy**, not “never investigate this family again.”

The king-safety rejection should likewise not be read as “king safety does not matter.” A later experiment must use a materially stronger model—such as attacker-count thresholds, weak-square/contact-check features, shelter/storm structure or shared/cached attack features—rather than simply retuning E5 v1 coefficients.

## Live experiment

### Conservative LMR v2 over E4

The unchanged conservative v2 policy first screened against killer-only production at:

- 31W / 49D / 20L;
- +38.37 +/-49.36 Elo;
- LOS 93.90%.

That result became stale immediately when E4 was accepted, so it did **not** authorize a merge. PR #44 is measuring the exact same frozen policy marginally over `main@2e4dcf1e10f482783af721ad09df113a63c5ba8b`:

- recursive negamax only;
- fourth and later quiet moves at depth >=3;
- never reduce captures, promotions, nodes in check or checking moves;
- one-ply reduction only;
- any reduced alpha improvement is immediately verified at full depth;
- ordinary PVS verification remains unchanged.

If positive over E4, LMR v2 still requires clean materialization and a 200-game acceptance before production.

## Decision rules

1. Correctness before Elo: formatting, strict Clippy, focused tests, reversible-state invariants and draw-strategy regressions run before a candidate match.
2. Strength is measured at equal resources with paired colour reversal and pinned openings/tooling.
3. A positive result against a stale baseline does not authorize a merge. Re-test marginal value against the strongest accepted stack.
4. Interaction matters. Independently positive evaluator/search features are stacked only after a direct marginal test when their effects can overlap.
5. Genuine draws remain score `0`; do not add ad-hoc draw-aversion bonuses. Negamax then naturally avoids draws while winning and seeks them while losing.
6. Temporary experiment workflows/patchers are not production architecture. Materialize the exact candidate, rerun correctness/evidence as needed, update the deterministic benchmark intentionally, then remove one-shot scaffolding before merge.
7. Negative experiments are retained as evidence. Revisit a rejected family only with a materially different hypothesis or a stronger baseline that makes the old result genuinely stale.
