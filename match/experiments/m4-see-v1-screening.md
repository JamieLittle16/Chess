# M4 SEE ordering v1 screening

This experiment compares SEE-based tactical ordering against the accepted staged MovePicker baseline
at commit `48bfebedb9aee3017ae8b3c5e56eb93352bd874f`.

The candidate changes ordering only. It does not use SEE for pruning. Tactical candidates are still
selected lazily by the accepted cheap tactical score; a candidate with negative static exchange
value is deferred behind quiet moves.

## Pre-match evidence

All reviewed benchmark scores and best moves remain unchanged. The deterministic Kiwipete depth-2
work count increases from 1,023 nodes on the accepted picker to 1,092 nodes with SEE ordering
(+69 nodes, approximately +6.7%). This is mildly negative search-shape evidence, and SEE itself also
has CPU cost, so the candidate is not accepted on deterministic evidence alone.

The paired match is being run because the fixed benchmark is deliberately small and SEE targets a
broader class of poisoned/losing captures. Equal-wall-clock games decide whether that broader
ordering benefit repays the local regression and SEE computation cost.

Protocol: `match/protocols/m4-see-v1-screening.json`.

Acceptance requires:

- `chess-search` correctness tests to pass independently of benchmark-signature drift;
- exact candidate/reference/Fastchess/opening hashes;
- 100 paired games with colour reversal under the frozen short-control protocol;
- a positive strength result strong enough to justify both the extra computation and the observed
  deterministic regression.

If the equal-time result is neutral or negative, SEE v1 ordering is rejected rather than retained
merely because SEE is conventional engine technology.
