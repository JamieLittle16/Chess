#!/usr/bin/env python3
"""Rewrite only the gestalt output head into a vectorisation-friendly exact form.

The candidate keeps the certified accumulator representation, SCReLU clamp, output weights,
and integer operation order. Per-neuron products are proven to fit i32 because
255^2 * 32768 = 2_130_739_200 < 2^31, so widening only the accumulated products to i64
avoids scalar i64 multiplies in the hot 3072-neuron forward pass while preserving exact scores.
"""

from __future__ import annotations

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one occurrence, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    path = Path("crates/chess-eval/src/gestalt.rs")
    text = path.read_text(encoding="utf-8")

    old = '''    fn score_accumulators(
        &self,
        white: &[i16; HIDDEN],
        black: &[i16; HIDDEN],
        side_to_move: Color,
    ) -> i32 {
        let (us, them) = match side_to_move {
            Color::White => (white, black),
            Color::Black => (black, white),
        };
        let mut output = 0_i64;
        for (index, &value) in us.iter().enumerate() {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[index]);
        }
        for (index, &value) in them.iter().enumerate() {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[HIDDEN + index]);
        }
        output /= i64::from(QA);
        output += i64::from(self.output_bias);
        output *= i64::from(SCALE);
        output /= i64::from(QA * QB);
        i32::try_from(output).expect("gestalt quantised output remains within i32")
    }
'''

    new = '''    fn score_accumulators(
        &self,
        white: &[i16; HIDDEN],
        black: &[i16; HIDDEN],
        side_to_move: Color,
    ) -> i32 {
        let (us, them) = match side_to_move {
            Color::White => (white, black),
            Color::Black => (black, white),
        };
        let mut output = output_dot(us, &self.output_weights[..HIDDEN]);
        output += output_dot(them, &self.output_weights[HIDDEN..]);
        output /= i64::from(QA);
        output += i64::from(self.output_bias);
        output *= i64::from(SCALE);
        output /= i64::from(QA * QB);
        i32::try_from(output).expect("gestalt quantised output remains within i32")
    }
'''
    text = replace_exact(text, old, new, label="output head")

    marker = '''/// Perspective coordinate frame. `bucket` selects physical weights; `mirror_files` distinguishes the
'''
    helper = '''#[inline]
fn output_dot(values: &[i16; HIDDEN], weights: &[i16]) -> i64 {
    debug_assert_eq!(weights.len(), HIDDEN);
    let mut sum0 = 0_i64;
    let mut sum1 = 0_i64;
    let mut sum2 = 0_i64;
    let mut sum3 = 0_i64;

    let (value_chunks, value_tail) = values.as_chunks::<4>();
    let (weight_chunks, weight_tail) = weights.as_chunks::<4>();
    debug_assert!(value_tail.is_empty());
    debug_assert!(weight_tail.is_empty());

    for (value, weight) in value_chunks.iter().zip(weight_chunks) {
        let c0 = i32::from(value[0]).clamp(0, QA);
        let c1 = i32::from(value[1]).clamp(0, QA);
        let c2 = i32::from(value[2]).clamp(0, QA);
        let c3 = i32::from(value[3]).clamp(0, QA);
        sum0 += i64::from(c0 * c0 * i32::from(weight[0]));
        sum1 += i64::from(c1 * c1 * i32::from(weight[1]));
        sum2 += i64::from(c2 * c2 * i32::from(weight[2]));
        sum3 += i64::from(c3 * c3 * i32::from(weight[3]));
    }
    sum0 + sum1 + sum2 + sum3
}

'''
    if text.count(marker) != 1:
        raise PatchError(f"helper marker: expected one occurrence, found {text.count(marker)}")
    text = text.replace(marker, helper + marker, 1)

    path.write_text(text, encoding="utf-8")
    print("applied exact i32-lane gestalt output head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
