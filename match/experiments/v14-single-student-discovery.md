# V14 single-accumulator H64 student — restrained discovery

Status: **1/12 qualifies for fresh replication; no model accepted yet**

The pilot H64 SCReLU student predicts a white-perspective correction on top of exact V13.  It was
trained from 1,827 Stockfish-19-labelled V13 self-play positions grouped by 80 opening roots.  This is
a small architecture/causality corpus, not the intended final NNUE corpus.

The search screen used opening roots 80-99, which were not among the 0-79 roots used to generate the
training corpus.  Every scale passed exact model provenance, incremental-accumulator rebuild tests and
API legality before games.

| Correction scale | Equal-node score | Naive Elo | Median NPS vs V13 |
| --- | ---: | ---: | ---: |
| 1/6 | 19.0/40 (47.5%) | -17.4 | 0.8600x |
| 1/8 | 19.0/40 (47.5%) | -17.4 | 0.8770x |
| 1/10 | 21.5/40 (53.75%) | +26.1 | 0.8791x |
| **1/12** | **23.0/40 (57.5%)** | **+52.5** | **0.8869x** |

The 1/12 result is discovery evidence only.  Forty games are far too few for an Elo claim, and the
~11.3% NPS cost means equal-time performance may differ materially from equal-node performance.

## Decision

- reject 1/6 and 1/8;
- do not promote 1/10;
- give 1/12 a fresh-opening replication, followed by equal-time testing only if replication remains
  positive;
- regardless of this pilot result, do not treat the 1,827-position corpus as final V14 training data.
  A serious evaluator needs a much larger, multi-source, whole-group-split, WDL/search-aligned corpus.
