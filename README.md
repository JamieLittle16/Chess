# Chess

A from-scratch, high-performance chess engine built around a deliberately modular architecture: a correctness-first chess core, incremental learned intelligence, sparse strategic search, and fast local tactical verification.

## Principles

- **Correctness before cleverness.** Chess rules and state transitions are independently testable and never delegated to learned components.
- **Strength is measured.** Search and evaluation ideas earn their place through reproducible benchmarks and paired-game Elo testing.
- **Hot paths stay small.** Move generation, make/unmake, tactical search, and incremental evaluation avoid routine allocation and unnecessary shared-state traffic.
- **Architecture follows ownership.** Protocols, browsers, training, search, evaluation, and chess rules have explicit boundaries.
- **Different by hypothesis, not by novelty.** We will explore a sparse strategic search graph, learned policy/value/uncertainty, and local tactical verification, but will not keep a weaker mechanism merely to differ from another engine.
- **Native and web share the engine.** The eventual UCI and WebAssembly targets use the same chess implementation and search logic.

## Current state

The repository is at **M0: Core Foundations**. The first implemented crate, `chess-core`, contains compact board-domain types, bitboards, position storage, and FEN parsing. Legal move generation and make/unmake are the next correctness boundary.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architectural constitution and subsystem boundaries.
- [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md) — correctness, performance, and Elo methodology.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — engineering rules for changes.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — staged route from core chess rules to the neural search engine and browser target.
- [`docs/adr/0001-architecture-v0.1.md`](docs/adr/0001-architecture-v0.1.md) — first architectural decision record.

## Development

The project pins Rust 1.98.1. Run the complete local gate with:

```sh
./scripts/check.sh
```
