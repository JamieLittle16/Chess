#!/usr/bin/env python3
"""Replace Hyperstition's twelve piece counts with the maintained occupancy count."""

from pathlib import Path


def main() -> int:
    path = Path("crates/chess-eval/src/hyperstition.rs")
    text = path.read_text(encoding="utf-8")
    old = """fn output_bucket(position: &Position) -> usize {
    let men = Color::ALL
        .into_iter()
        .flat_map(|color| PieceKind::ALL.into_iter().map(move |kind| (color, kind)))
        .map(|(color, kind)| position.pieces(color, kind).count() as usize)
        .sum::<usize>();
    men.saturating_sub(2).div_euclid(4).min(OUTPUT_BUCKETS - 1)
}
"""
    new = """fn output_bucket(position: &Position) -> usize {
    let men = position.occupied().count() as usize;
    men.saturating_sub(2).div_euclid(4).min(OUTPUT_BUCKETS - 1)
}
"""
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one output_bucket implementation, found {text.count(old)}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("applied aggregate-occupancy output-bucket fastpath")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
