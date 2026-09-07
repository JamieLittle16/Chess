# V14 H128 Chess768 accumulator carry — whole-search cost

This experiment threads a production-shaped, two-perspective, 128-wide Chess768 accumulator through the exact final V13 search using deterministic synthetic weights. The network score is never read, so search behaviour must remain exact V13. The purpose is to measure the unavoidable state-update tax before spending training compute.

## Qualification

Across 24 frozen opening positions, 50,000 nodes/position, three repetitions:

- every candidate move/score/depth/node signature exactly matched V13;
- median candidate/control NPS ratio: **0.903109**;
- individual ratios: **0.903109, 0.903509, 0.902679**.

Representative aggregate NPS was about 1.625M for V13 versus 1.468M with the score-disabled accumulator.

## Interpretation

Carrying and sparsely updating H128 costs about **9.69% whole-search NPS** before paying integer output-evaluation cost. This is a meaningful but tractable hurdle and is dramatically smaller than the old full-refresh learned-evaluator regression.

A trained compact evaluator is not accepted merely because this cost looks manageable. It must recover this tax through substantially stronger equal-node play and still win at the actual equal-time competition control.

## Decision

**H128 remains viable for training and real-evaluator qualification.** Width selection remains open across the frozen 64/96/128/192 student ladder.
