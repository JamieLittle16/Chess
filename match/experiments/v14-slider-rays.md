# V14 precomputed slider rays

Status: **rejected**

Hypothesis: replace repeated file/rank boundary arithmetic in slider attack queries, full pseudo move
generation, tactical pseudo move generation and shared legality-context ray scans with precomputed
near-to-far square lists. Direction order was preserved exactly.

## Correctness

All semantic gates passed against exact final V13 BEST:

- ordered legal + tactical move-generation parity on 25,000 deterministic random legal positions;
- directed castling/en-passant/pin/check geometry parity;
- start-position perft depth 4 = 197,281 and depth 5 = 4,865,609;
- 120/120 fixed-node search results byte-for-byte identical.

This makes the performance comparison clean: the candidate changed execution cost, not chess.

## Performance

Fixed-node search, 40 roots x 3 repetitions at 30,000 nodes/root:

- rep 0: 0.99145x candidate throughput versus V13;
- rep 1: 0.99446x;
- rep 2: 0.99018x;
- median: **0.99145x** (~0.86% slower).

Direct legal-move-generation microbenchmark:

- V13 clustered around ~474 ns/call;
- precomputed rays clustered around ~486.5 ns/call;
- candidate is ~2.6% slower in this benchmark.

## Decision

Reject. In Numba, the original compact coordinate/ray loops outperform the extra indexed global-array
loads despite doing more arithmetic. Do not carry the ray tables into V14 unless a materially
different bitboard/occupancy representation changes the cost model.
