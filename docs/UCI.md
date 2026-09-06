# UCI Interface

Status: **M3 interruptible worker + standard game clocks**

The UCI target makes the reference engine usable by standard chess tooling while keeping protocol concerns outside chess correctness and search. Protocol text is translated into `chess-engine` operations; `chess-uci` does not own chess rules or search algorithms.

## Dependency boundary

```text
chess-core → chess-eval → chess-search → chess-engine → chess-uci
```

`chess-uci` is allowed to allocate strings and parse text because it is not a search hot path. It must not infer castling, en-passant or promotion legality independently. Incoming coordinate moves are matched against `Position::legal_moves()` and only the matching semantic `ChessMove` is applied.

Search policy follows the same ownership rule. UCI parses requested limits and clocks, selects the clock belonging to the actual side to move, and maps that data into `chess-engine::ClockState` / `SearchLimits`. Wall-clock budgeting itself is engine policy, not protocol policy.

## Runtime ownership

The executable uses a long-lived worker thread:

```text
stdin / protocol thread
    │
    ├── ordinary command channel ───────────────┐
    │                                           ▼
    └── cloneable StopToken ───────────────► UCI worker
                                                │
                                                └── owns UciSession
                                                     owns Engine
                                                     owns Searcher + TT
```

The mutable engine is never shared behind a mutex. The worker remains its sole owner for the lifetime of the executable. The stdin thread retains only a command sender and a clone of the cooperative stop signal.

`stop` is handled directly on the stdin thread by setting that token. It therefore does not need to wait behind the currently running `go` command. Before a new `go` is admitted, the input thread resets the token; doing the reset before enqueueing prevents a subsequent fast `stop` from being lost in the race before the worker begins searching.

EOF and `quit` also set the stop signal, so a long depth-only search cannot keep the process alive indefinitely during shutdown.

The library's ordinary `UciSession::new()` remains synchronous and keeps pure fixed-depth search on the zero-overhead `NeverStop` path. `UciSession::new_interruptible()` is the executable-oriented mode that routes every search through the shared stop token.

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
- `go wtime MS btime MS [winc MS] [binc MS] [movestogo N]`
- compatible combinations of depth, node, fixed-time and game-clock limits;
- asynchronous `stop`
- `quit`

Move text uses standard UCI long algebraic coordinate form such as `e2e4`, `e7e8q` and `e1g1`.

A search emits a standard `info depth ... score ... nodes ...` line followed by `bestmove ...`. Mate-range internal scores are translated to `score mate N`; ordinary scores are emitted as centipawns.

## Game-clock mapping

UCI owns only the syntactic clock packet. For a White-to-move position, `wtime`/`winc` are selected; for a Black-to-move position, `btime`/`binc` are selected. If clock fields are supplied without the relevant side's remaining time, the command is rejected explicitly rather than silently borrowing the opponent's clock.

The selected values become:

```text
ClockState {
    remaining,
    increment,
    moves_to_go,
}
```

`ClockState::allocated_movetime()` then applies the current M3 engine policy:

1. reserve 5% of the remaining clock;
2. divide the spendable remainder across `movestogo`, or 30 moves when it is absent;
3. add 75% of one increment;
4. cap the result at the spendable clock after the reserve.

This is intentionally a simple, pinned baseline rather than mature time management. Later policies can be compared by paired games without changing UCI parsing.

If both explicit `movetime` and a game clock are supplied, the smaller hard deadline wins. Node and depth constraints remain independent; search therefore stops when the first active constraint fires. Dynamically limited searches without an explicit depth use a conservative depth safety cap of 64.

## Interrupted-iteration semantics

Iterative deepening publishes only fully completed iterations. If a node, deadline, or external stop fires part-way through the next depth, `bestmove` and score come from the last completed depth while the reported node count includes the partial work that was actually performed.

If interruption happens before depth one completes, the engine returns a legal depth-zero fallback whenever legal moves exist. Search interruption therefore cannot expose a half-searched root result as though it were complete, and every speculative move is unmade before returning.

## Transactionality

A `position` command is assembled in a temporary `Position`. The engine's live game position is replaced only after the full FEN and every supplied move have validated. One malformed or illegal move therefore cannot leave the engine in a half-applied position.

## Deliberate current limits

This is not yet the final tournament UCI surface. In particular:

- `go infinite` and ponder are not implemented;
- there are no configurable UCI options yet;
- MultiPV is not implemented;
- commands other than `stop` are serialized through the engine worker, so `isready` received during a long active search currently waits for that search to return;
- callers should not issue a second `go` while a search is active without stopping the first one;
- the M3 game-clock allocator is deliberately conservative and has not yet been tuned by Elo testing.

Unsupported `go` limits are rejected explicitly rather than approximated incorrectly.

The next qualification work audits draw/history semantics and then establishes reproducible match testing. Time-allocation sophistication belongs after that baseline is measurable.

## Evidence gates

CI tests require:

1. canonical `uci`/`isready` responses;
2. legal `position startpos moves ...` application;
3. transactional rejection of an illegal move sequence;
4. promotion notation round-tripping;
5. fixed-depth `go` returning a legal move in the unchanged root;
6. node-limited search returning a legal fallback/result without corrupting the root;
7. zero-movetime interruption returning a legal fallback without corrupting the root;
8. an interruptible depth search honoring an externally shared stop token;
9. combined fixed limits preserving all constraints;
10. White and Black clock packets selecting the actual side-to-move time/increment;
11. `movestogo`, explicit `movetime`, game clocks and node limits composing conservatively;
12. incomplete side-to-move clocks and unsupported/malformed requests being rejected explicitly;
13. the threaded executable compiling under strict Clippy with the engine remaining single-owner;
14. workspace formatting, debug tests, release tests and the pinned reference-search signature remaining green.
