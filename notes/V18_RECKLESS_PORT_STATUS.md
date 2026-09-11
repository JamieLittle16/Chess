# V18 Reckless-port status

- Frozen control: exact PUNCH133.
- SEE ordering ablation: 18.5/32 (57.81%, about +55 Elo) at paired 30+0.5, zero failures.
- Root TT rewrites, aspiration, full-qsearch H64: rejected by paired selfplay.
- Existing V18 already has persistent main+continuation quiet history and history-adjusted verified LMR; do not duplicate them.
- Live qualification: true staged capture ordering (good captures -> quiets -> bad captures), with tactical-metadata guards for killer/history semantics.
- Next isolated lane: compact capture history appended to the existing persistent history storage, so no recursive signature changes are required.
