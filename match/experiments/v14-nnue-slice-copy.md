# V14 NNUE shadow slice-copy transport

Status: **rejected**

Hypothesis: replace explicit per-neuron accumulator copies with contiguous NumPy slice assignment so
Numba/LLVM could lower the parent-to-child transport to a memcpy-like operation.

All semantic gates remained green:

- 5,000 incremental transitions vs full rebuild at every tested width;
- 120/120 fixed-node V13 search signatures identical at H64/H96/H128/H192.

The performance result was strongly negative:

| Width | Original dual shadow overhead | Slice-copy overhead |
| ---: | ---: | ---: |
| 64 | 17.42% | **54.43%** |
| 96 | 20.16% | **79.11%** |
| 128 | 22.06% | **94.73%** |
| 192 | 27.40% | **139.17%** |

The slice form evidently introduces substantial array/slice machinery in this compiled hot path and
does not behave like a cheap raw memcpy. Keep the explicit scalar copy/update loop as the current
best dual-perspective transport implementation.

Do not revisit generic NumPy slice assignment for per-edge NNUE state without first demonstrating a
lowered-code reason that its cost model has changed.
