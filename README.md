# Chess

A from-scratch, high-performance chess engine built around a deliberately modular architecture: a correctness-first chess core, a measured classical reference engine, incremental learned intelligence, sparse strategic search, and fast local tactical verification.

## Principles

- **Correctness before cleverness.** Chess rules and state transitions are independently testable and never delegated to learned components.
- **Strength is measured.** Search and evaluation ideas earn their place through reproducible benchmarks and paired-game Elo testing.
- **Hot paths stay small.** Move generation, make/unmake, tactical search, and incremental evaluation avoid routine allocation and unnecessary shared-state traffic.
- **Architecture follows ownership.** Protocols, browsers, training, search, evaluation, and chess rules have explicit boundaries.
- **Different by hypothesis, not by novelty.** We will explore a sparse strategic search graph, learned policy/value/uncertainty, and local tactical verification, but will not keep a weaker mechanism merely to differ from another engine.
- **Native and web share the engine.** UCI and eventual WebAssembly targets consume the same chess and search implementation.

## Current state

The repository is at **M3: Classical Reference Engine**.

The chess layer is functional: `chess-core` parses FEN, generates legal moves, handles castling/en-passant/promotions, makes and unmakes moves reversibly, passes published perft gates, and maintains independently reconstructable Zobrist identity. It also exposes a separate rule-correct repetition identity so unusable or king-pinned en-passant metadata does not create false distinctions between repeated positions.

Above it, `chess-eval` provides the deliberately simple material reference evaluator and `chess-search` provides deterministic negamax/alpha-beta, iterative deepening, bounded transposition storage, mate/stalemate handling, threefold/50-move/dead-material draw adjudication, reversible root search and cooperative cancellation. Search keeps speculative repetition history in a fixed-capacity path buffer rather than allocating in recursion.

`chess-engine` owns persistent game/search state, actual game repetition history, node/deadline control and protocol-neutral game-clock budgeting. `chess-uci` runs the engine on a single-owner worker thread, exposes asynchronous `stop`, fixed limits and standard UCI clocks, and preserves repetition history transactionally through `position ... moves ...` commands.

The deterministic draw-aware reference benchmark is `reference-search-v2`, currently pinned at `0x1a149495c23a7d8e` in CI.

M3 now also has repository-owned paired-game qualification tooling: `match/protocols/m3-baseline-v1.json` freezes the first finite-time experiment settings and `scripts/match_harness.py` wraps Fastchess while recording exact engine/runner/opening hashes, git/environment provenance, the command line, PGN, raw output and UCI logs. CI tests the harness without running time-sensitive tournaments.

This is now a real but intentionally weak, rule-correct playable engine baseline. The remaining M3 boundary is to freeze the opening corpus and retain the first measured external baseline; strength work follows that measurement boundary.

## Workspace

```text
chess-core
    ↑
chess-eval
    ↑
chess-search
    ↑
chess-engine
    ↑
chess-uci
```

Future WASM and other frontends branch from the orchestration/search layers rather than duplicating chess rules.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architectural constitution and subsystem boundaries.
- [`docs/STATE_TRANSITIONS.md`](docs/STATE_TRANSITIONS.md) — reversible move-state design and reference-oracle strategy.
- [`docs/POSITION_IDENTITY.md`](docs/POSITION_IDENTITY.md) — TT identity, repetition identity and deterministic incremental Zobrist hashing.
- [`docs/PERFT.md`](docs/PERFT.md) — legal-chess reference positions and acceptance gates.
- [`docs/REFERENCE_ENGINE.md`](docs/REFERENCE_ENGINE.md) — evaluator, draw-aware alpha-beta, iterative deepening and TT baseline.
- [`docs/UCI.md`](docs/UCI.md) — supported UCI surface, worker ownership, clocks and transactional history.
- [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md) — correctness, performance and Elo methodology.
- [`docs/MATCH_QUALIFICATION.md`](docs/MATCH_QUALIFICATION.md) — reproducible paired-game protocol, provenance manifest and evidence rules.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — engineering rules for changes.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — staged route from core chess rules to the neural search engine and browser target.
- [`docs/adr/0001-architecture-v0.1.md`](docs/adr/0001-architecture-v0.1.md) — first architectural decision record.

## Development

The project pins Rust 1.98.1. Run the complete local gate with:

```sh
./scripts/check.sh
```

Build and launch the UCI engine with:

```sh
cargo run --release -p chess-uci
```

The executable supports `go depth N`, `go nodes N`, `go movetime MS`, standard `wtime`/`btime`/increment/`movestogo` clocks, compatible limit combinations, and asynchronous `stop`. Search state remains single-owner on the engine worker rather than shared behind a mutex.

Prepare a reproducible match with:

```sh
python3 scripts/match_harness.py \
  --candidate /path/to/candidate \
  --reference /path/to/reference \
  --fastchess /path/to/fastchess \
  --openings /path/to/openings.epd \
  --output-dir /new/results/directory \
  --dry-run
```

Remove `--dry-run` only after inspecting the generated manifest and exact Fastchess command. Match results are evidence only when the run completes and its protocol, opponent, opening-suite identity and uncertainty are retained with the raw outputs.
