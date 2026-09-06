# UCI Interface

Status: **M3 minimal synchronous interface**

The first UCI target exists to make the reference engine usable by standard chess tooling as early as possible. It is deliberately thin: protocol text is translated into `chess-engine` operations and never owns chess rules or search algorithms.

## Dependency boundary

```text
chess-core → chess-eval → chess-search → chess-engine → chess-uci
```

`chess-uci` is allowed to allocate strings and parse text because it is not a search hot path. It must not infer castling, en-passant or promotion legality independently. Incoming coordinate moves are matched against `Position::legal_moves()` and only the matching semantic `ChessMove` is applied.

## Supported commands

The initial executable supports:

- `uci`
- `isready`
- `ucinewgame`
- `position startpos [moves ...]`
- `position fen <six FEN fields> [moves ...]`
- `go depth N`
- `stop` as a no-op when no asynchronous search is active
- `quit`

Move text uses standard UCI long algebraic coordinate form such as `e2e4`, `e7e8q` and `e1g1`.

A search emits a standard `info depth ... score ... nodes ...` line followed by `bestmove ...`. Mate-range internal scores are translated to `score mate N`; ordinary scores are emitted as centipawns.

## Transactionality

A `position` command is assembled in a temporary `Position`. The engine's live game position is replaced only after the full FEN and every supplied move have validated. One malformed or illegal move therefore cannot leave the engine in a half-applied position.

## Deliberate current limits

This is not yet a complete tournament UCI implementation. In particular:

- search is synchronous;
- only fixed-depth `go` is implemented;
- `stop` cannot interrupt an already-running search on the same stdin thread;
- clock/movetime/node/infinite limits are not implemented yet;
- there are no configurable UCI options yet;
- ponder and MultiPV are not implemented.

These limits are explicit rather than approximated incorrectly. The next orchestration milestone introduces search limits/time control and an interruptible worker boundary.

## Evidence gates

CI tests require:

1. canonical `uci`/`isready` responses;
2. legal `position startpos moves ...` application;
3. transactional rejection of an illegal move sequence;
4. promotion notation round-tripping;
5. `go depth 1` returning a move that is legal in the unchanged root;
6. `quit` terminating the session state;
7. workspace formatting, strict Clippy, debug tests and release tests remaining green.
