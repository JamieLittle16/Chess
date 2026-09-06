# UCI Interface

Status: **M3 synchronous search-limit interface**

The UCI target makes the reference engine usable by standard chess tooling while keeping protocol concerns outside chess correctness and search. Protocol text is translated into `chess-engine` operations; `chess-uci` does not own chess rules or search algorithms.

## Dependency boundary

```text
chess-core → chess-eval → chess-search → chess-engine → chess-uci
```

`chess-uci` is allowed to allocate strings and parse text because it is not a search hot path. It must not infer castling, en-passant or promotion legality independently. Incoming coordinate moves are matched against `Position::legal_moves()` and only the matching semantic `ChessMove` is applied.

Search policy follows the same ownership rule. UCI parses requested limits into `chess-engine::SearchLimits`; wall-clock/node stopping is implemented by engine orchestration and cooperative checks in `chess-search` rather than by protocol-specific search code.

## Supported commands

The executable currently supports:

- `uci`
- `isready`
- `ucinewgame`
- `position startpos [moves ...]`
- `position fen <six FEN fields> [moves ...]`
- `go depth N`
- `go nodes N`
- `go movetime MS`
- compatible combinations such as `go depth 12 nodes 500000 movetime 1000`
- `stop` as a no-op when no asynchronous search is active
- `quit`

Move text uses standard UCI long algebraic coordinate form such as `e2e4`, `e7e8q` and `e1g1`.

A search emits a standard `info depth ... score ... nodes ...` line followed by `bestmove ...`. Mate-range internal scores are translated to `score mate N`; ordinary scores are emitted as centipawns.

When multiple supported `go` constraints are supplied, search stops when the first active constraint fires. Node- or movetime-only searches use a conservative depth safety cap of 64; an explicit `depth N` replaces that cap.

Pure fixed-depth search deliberately stays on the ordinary `NeverStop` path, so it does not pay atomic/deadline checks at every searched node. Cooperative control is activated only for node or wall-clock limits.

## Interrupted-iteration semantics

Iterative deepening publishes only fully completed iterations. If a node or movetime limit fires part-way through the next depth, `bestmove` and score come from the last completed depth while the reported node count includes the partial work that was actually performed.

If the limit fires before depth one completes, the engine returns a legal depth-zero fallback whenever legal moves exist. Search interruption therefore cannot expose a half-searched root result as though it were complete, and every speculative move is unmade before returning.

## Transactionality

A `position` command is assembled in a temporary `Position`. The engine's live game position is replaced only after the full FEN and every supplied move have validated. One malformed or illegal move therefore cannot leave the engine in a half-applied position.

## Deliberate current limits

This is not yet a complete tournament UCI implementation. In particular:

- command handling is synchronous;
- `stop` cannot interrupt an already-running search on the same stdin thread;
- full clock allocation (`wtime`, `btime`, `winc`, `binc`, `movestogo`) is not implemented yet;
- `go infinite` and ponder are not implemented;
- there are no configurable UCI options yet;
- MultiPV is not implemented.

Unsupported `go` limits are rejected explicitly rather than approximated incorrectly.

The next UCI/orchestration milestone is a long-lived search worker with a cloneable stop token. That will allow the stdin/protocol thread to process `stop` while the engine worker is searching, while keeping the mutable `Engine` and its transposition table under one clear owner.

## Evidence gates

CI tests require:

1. canonical `uci`/`isready` responses;
2. legal `position startpos moves ...` application;
3. transactional rejection of an illegal move sequence;
4. promotion notation round-tripping;
5. fixed-depth `go` returning a legal move in the unchanged root;
6. node-limited search returning a legal fallback/result without corrupting the root;
7. zero-movetime interruption returning a legal fallback without corrupting the root;
8. combined `depth`/`nodes`/`movetime` parsing preserving all limits;
9. unsupported or malformed `go` requests being rejected explicitly;
10. workspace formatting, strict Clippy, debug tests, release tests and the pinned reference-search signature remaining green.
