#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, random
from pathlib import Path


def expected_score(rating: float, opp: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opp - rating) / 400.0))


def fit_rating(rows: list[dict], override_points: list[float] | None = None) -> float:
    best_r, best_ll = None, -1e300
    for half in range(2400, 6401):
        r = half / 2.0
        ll = 0.0
        for i, row in enumerate(rows):
            n = float(row['games'])
            pts = float(row['points'] if override_points is None else override_points[i])
            p = min(1 - 1e-12, max(1e-12, expected_score(r, float(row['stockfish_uci_elo']))))
            ll += pts * math.log(p) + (n - pts) * math.log(1.0 - p)
        if ll > best_ll:
            best_ll, best_r = ll, r
    assert best_r is not None
    return best_r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--seed', type=int, default=20260910)
    ap.add_argument('--bootstrap', type=int, default=10000)
    args = ap.parse_args()
    summaries = sorted(args.root.rglob('summary.json'))
    rows = [json.loads(p.read_text()) for p in summaries]
    if len(rows) < 2:
        raise SystemExit(f'need >=2 rung summaries, found {len(rows)}')
    rows.sort(key=lambda r: r['stockfish_uci_elo'])
    centre = fit_rating(rows)
    rng = random.Random(args.seed)
    boots = []
    for _ in range(args.bootstrap):
        pts = []
        for row in rows:
            pairs = row['pair_scores']
            sampled = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
            pts.append(sum(sampled))
        boots.append(fit_rating(rows, pts))
    boots.sort()
    lo = boots[int(0.025 * len(boots))]
    hi = boots[min(len(boots)-1, int(0.975 * len(boots)))]
    out = {
        'fit_model': 'fixed 400-Elo logistic expectation; pair bootstrap across colour-reversed openings',
        'fitted_v18_rating': centre,
        'bootstrap_95': [lo, hi],
        'rungs': [
            {
                'stockfish_uci_elo': r['stockfish_uci_elo'],
                'wdl': [r['wins'], r['draws'], r['losses']],
                'score': r['score'],
                'relative_elo': r['relative_elo'],
                'implied_v18_rating': r['implied_v18_rating'],
                'rung_ci': r['relative_elo_pair_bootstrap_95'],
            } for r in rows
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps(out, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
