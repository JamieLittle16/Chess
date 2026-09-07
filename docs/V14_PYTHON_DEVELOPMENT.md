# Python V14 development programme

V14 is an architectural generation built from the exact CI-qualified V13 package. V13 remains the immutable control until a candidate clears every required gate.

## Frozen V13 control

- Branch/commit: `analysis/v13-final-best-20260907` / `b98735d0f9f0a48c0e2e47478bf6295ded286c3a`
- Final package SHA-256: `acf6ba72c95fa61fb6b54245f2e24ab9aa1665950b29cecf421ac3c7ab9a738a`
- `numba_core.py`: `0306e8145a453d91b9b5ac92e9980931510d9e18f8ba598a7548d08b85165c35`
- `numba_search.py`: `401f6580028a72361286bd99bee1f0022c74e6c8a65da8acd47448835a1ff360`
- residual: `7d0fc5f7a186e79317cf12a2ff285d7716c651fbd045c53d65a3cc6eb1b15319`

No V14 experiment may silently modify the V13 control. Experiments reconstruct the exact control independently and apply one named patch only to the candidate.

## Qualification philosophy

Each behavioural candidate must pass, in order:

1. exact package reconstruction/hash checks;
2. syntax and search-call-arity checks;
3. competition API legality smoke;
4. unchanged-core hash checks when the experiment claims to be search-only;
5. deterministic fixed-node reproducibility;
6. fixed-node throughput/NPS regression guard;
7. paired colour-reversed game screen on frozen openings;
8. fresh-opening confirmation and then the repository SPRT protocol before acceptance.

Discovery screens are not merge evidence. A candidate that looks positive on the first book is still provisional until it replicates on fresh openings.

## V14-A: main quiet history

The first experiment is deliberately narrow. It adds a bounded side/from/to quiet-history table, uses the table only to order ordinary quiet moves, and rewards quiet beta cutoffs with a gravity-style bounded update.

It explicitly does **not** change:

- V13 evaluation or the 1/6 learned residual;
- qsearch;
- legality/move generation;
- RFP or late-quiet futility margins;
- the accepted adaptive verified LMR v3 schedule;
- TT/repetition/50-move semantics;
- time management.

This is a probe for whether V13 is leaving meaningful strength on the table through quiet ordering. If it fails, it is discarded without contaminating V13. If it succeeds, continuation history and history-conditioned LMR will be tested as separate follow-on hypotheses rather than bundled into the first result.

## Larger V14 tracks

In parallel with search experiments, V14 will consume the M6/Rust data and teacher infrastructure to train a compact Python-specific incremental NNUE student. The Python deployment target is strength per unit CPU time, not architectural identity with the larger Rust NNUE. Evaluator replacement will be qualified first at equal nodes and then at the actual competition time control.
