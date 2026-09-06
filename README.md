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

The chess layer is already functional: `chess-core` parses FEN, generates legal moves, handles castling/en-passant/promotions, makes and unmakes moves reversibly, passes published perft gates, and maintains independently reconstructable Zobrist identity.

Above it, `chess-eval` provides the deliberately simple material reference evaluator and `chess-search` provides deterministic negamax/alpha-beta, iterative deepening, bounded transposition storage, mate/stalemate handling, reversible root search and cooperative cancellation. `chess-engine` owns persistent game/search state plus depth/node/movetime orchestration, and `chess-uci` exposes the standard command-line engine interface.

This is now a real but intentionally weak playable engine baseline. Strength work comes after the correctness, timing and measurement interfaces are stable.

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
- [`docs/POSITION_IDENTITY.md`](docs/POSITION_IDENTITY.md) — deterministic incremental Zobrist identity.
- [`docs/PERFT.md`](docs/PERFT.md) — legal-chess reference positions and acceptance gates.
- [`docs/REFERENCE_ENGINE.md`](docs/REFERENCE_ENGINE.md) — evaluator, alpha-beta, iterative deepening and TT baseline.
- [`docs/UCI.md`](docs/UCI.md) — supported UCI surface and current deliberate limits.
- [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md) — correctness, performance, and Elo methodology.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — engineering rules for changes.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — staged route from core chess rules to the neural search engine and browser target.
- [`docs/adr/0001-architecture-v0.1.md`](docs/adr/0001-architecture-v0.1.md) — first architectural decision record.

## Development

The project pins Rust 1.98.1. Run the complete local gate with:

```sh
./scripts/check.sh
```

Once the UCI target is built, it can be launched with:

```sh
cargo run --release -p chess-uci
```

The synchronous UCI surface currently supports `go depth N`, `go nodes N`, `go movetime MS`, and compatible combinations. The next orchestration boundary is an asynchronous worker so `stop` and full clock allocation can operate while search is live.
