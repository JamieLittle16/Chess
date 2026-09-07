# V14 compact Chess768 runtime substrate — qualified

This branch certifies the Python/Numba deployment mechanics for the compact V14 evaluator before any learned checkpoint is allowed to affect search.

## Frozen evaluator contract

- dual global perspectives
- Bullet `Chess768` feature mapping pinned to commit `629ee50000b2afb7b3337595401c830d3b1e0f42`
- SCReLU integer inference
- `QA=255`, `QB=64`, eval scale `400`
- Bullet `quantised.bin` little-endian i16 loader and 64-byte-padding contract

Because Chess768 is not king-bucketed, king moves are ordinary sparse feature deltas; no perspective rebuild is required.

## Correctness qualification

Using deterministic synthetic H=128 weights:

- all 1,536 signed-piece / square / perspective feature-map cases matched the independent reference;
- 5,000 deterministic random legal move transitions matched full accumulator refresh exactly for both perspectives;
- directed special-move coverage included castling, en-passant and every promotion form selected by the legal generator;
- random coverage additionally observed 4 castlings, 2 en-passants and 29 promotions;
- quantised integer inference matched an independent signed-truncation-toward-zero reference exactly;
- V13 production search was not modified.

## Standalone warmed runtime measurements

| H | sparse two-perspective delta | full two-perspective refresh | delta / refresh | integer eval |
|---:|---:|---:|---:|---:|
| 64 | 56.34 ns | 380.47 ns | 0.1481 | 101.54 ns |
| 96 | 64.84 ns | 517.04 ns | 0.1254 | 136.16 ns |
| 128 | 84.63 ns | 676.39 ns | 0.1251 | 171.96 ns |
| 192 | 132.83 ns | 1187.98 ns | 0.1118 | 233.71 ns |

These are microbenchmarks, not whole-engine NPS claims. The separate score-disabled search-cost experiment measures the actual tree-level accumulator tax.

## Decision

**Qualified as V14 infrastructure.** This does not promote any learned evaluator. A real checkpoint must still beat final V13 at equal nodes and then equal time before integration.
