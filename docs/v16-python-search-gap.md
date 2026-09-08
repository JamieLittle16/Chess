# Search gap audit: Python V14 vs Rust V15

Python V14 already has a rule-aware TT, PVS, conservative RFP, late-quiet futility, killers and adaptive verified LMR. A material production-search difference remains: Rust V15 has learned quiet main history plus one-ply continuation history.

Rust's accepted policy uses compact `(piece kind, destination)` move contexts. It maintains side-specific main history and `(previous context, current context)` continuation history with bounded gravity updates. Scout-node quiet fail-highs receive a positive depth-scaled update; searched quiets that fail to cut receive a half-sized malus. The learned score ranks ordinary quiets and also adjusts the LMR reduction by one ply for strongly positive/negative history.

The older Python `v13-history-ordering` experiment does not test this mechanism: it used a simpler side/from/to table on an older quarter-residual V13 candidate and no continuation context. The exact Rust-style port is therefore a distinct qualification lane.
