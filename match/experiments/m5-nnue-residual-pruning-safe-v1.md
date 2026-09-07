# M5 residual NNUE pruning-safe diagnostic v1

Status: **diagnostic in progress**

The first equal-time full-refresh residual NNUE screen scored 4-79-17 (12.5%), approximately -338 +/- 95 Elo versus the identical classical binary. Its median NPS was approximately half of classical, but the loss was too large to attribute to throughput without an equal-work test.

This diagnostic tests a second interaction at equal work: the accepted reverse/late futility margins were qualified against the classical static evaluator. The residual NNUE is therefore used only where ordinary static leaf evaluation is requested; the futility-pruning oracle remains `evaluate_classical`.

The model, scale, opening suite and engine source remain frozen. Both sides receive 25,000 nodes per move. The candidate alone enables the residual model; the reference is the identical patched executable with the residual disabled. Because `evaluate_classical == evaluate` when the model is disabled, this patch does not change the reference's pruning semantics.

Acceptance is not implied by a positive result here. This experiment isolates whether coupling a newly learned evaluator to already-tuned pruning margins accounts for a meaningful part of the playing-strength regression before incremental inference work proceeds.
