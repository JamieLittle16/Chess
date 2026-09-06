# Development Contract

## Change rules

1. Keep dependency direction explicit; lower layers do not import higher-layer concerns.
2. Do not add an abstraction merely because it might be useful later. Add it when two real responsibilities need a boundary.
3. Every correctness-sensitive optimisation needs tests that would fail if its invariant is broken.
4. Every performance-sensitive change includes before/after measurement once a relevant benchmark exists.
5. Every claimed strength improvement is eventually validated through paired games; tactical anecdotes are not Elo evidence.
6. Public APIs prefer compact domain types over primitive soup (`Square` rather than unrelated `u8`s).
7. Search hot paths avoid heap allocation, reference counting, dynamic dispatch and coarse locks unless measurement demonstrates a net benefit.
8. Derived position/evaluation caches mutate through narrow APIs so they cannot drift independently.
9. New architectural decisions or reversals get an ADR under `docs/adr/`.
10. Documentation changes with architecture, not months afterwards.

## Required local gate

```sh
./scripts/check.sh
```

CI runs formatting, clippy, debug tests and release tests.

## Commit discipline

Prefer changes that do one architectural or behavioural thing and can be reviewed independently. Commit messages should explain the outcome, not the editing operation.

Examples:

- `core: encode squares and compact moves`
- `core: add reversible castling state`
- `movegen: validate sliders against reference generator`
- `search: add deterministic depth-one negamax baseline`

## Performance changes

Before making code more complex, establish the workload and metric. Preserve a simple implementation as a reference test when that meaningfully increases confidence.

Do not optimise based only on NPS if a change alters what counts as a node. Prefer equal-time Elo for whole-engine decisions.
