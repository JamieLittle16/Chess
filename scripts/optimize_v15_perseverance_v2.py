#!/usr/bin/env python3
"""Safe, bit-exact hot-path optimisations for the V15 perseverance evaluator."""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-eval/src/perseverance.rs")
text = path.read_text()

text = replace_once(
    text,
    """        let mut ft = [0_u8; HIDDEN];
        activate_half(us, &mut ft[..HALF_HIDDEN]);
        activate_half(them, &mut ft[HALF_HIDDEN..]);

        let mut l1_sums = [0_i32; L2_SIZE];
        for (input_index, &input) in ft.iter().enumerate() {
            if input == 0 {
                continue;
            }
            let start = (input_index * OUTPUT_BUCKETS + output_bucket) * L2_SIZE;
            let weights = &self.l1_weights[start..start + L2_SIZE];
            for (sum, &weight) in l1_sums.iter_mut().zip(weights) {
                *sum += i32::from(input) * i32::from(weight);
            }
        }
""",
    """        // Fuse pair activation into L1 accumulation. Integer addition order within every output
        // is unchanged from the materialised-buffer implementation, so this is bit-exact while
        // avoiding a 2 KiB stack buffer and a second full hidden-layer pass.
        let mut l1_sums = [0_i32; L2_SIZE];
        for (perspective_index, accumulator) in [us, them].into_iter().enumerate() {
            for index in 0..HALF_HIDDEN {
                let left = i32::from(accumulator[index]).clamp(0, QA);
                let right = i32::from(accumulator[HALF_HIDDEN + index]).clamp(0, QA);
                let input = (left * right) >> FT_SHIFT;
                if input == 0 {
                    continue;
                }
                let input_index = perspective_index * HALF_HIDDEN + index;
                let start = (input_index * OUTPUT_BUCKETS + output_bucket) * L2_SIZE;
                let weights = &self.l1_weights[start..start + L2_SIZE];
                for (sum, &weight) in l1_sums.iter_mut().zip(weights) {
                    *sum += input * i32::from(weight);
                }
            }
        }
""",
    "fused FT and L1",
)

text = replace_once(
    text,
    """fn activate_half(accumulator: &[i16; HIDDEN], output: &mut [u8]) {
    debug_assert_eq!(output.len(), HALF_HIDDEN);
    for index in 0..HALF_HIDDEN {
        let left = i32::from(accumulator[index]).clamp(0, QA);
        let right = i32::from(accumulator[HALF_HIDDEN + index]).clamp(0, QA);
        let product = (left * right) >> FT_SHIFT;
        output[index] = u8::try_from(product).expect(\"SCReLU pair product fits u8\");
    }
}

""",
    "",
    "remove obsolete activation helper",
)

text = replace_once(
    text,
    """fn output_bucket(position: &Position) -> usize {
    let men: usize = Color::ALL
        .into_iter()
        .flat_map(|color| PieceKind::ALL.into_iter().map(move |kind| (color, kind)))
        .map(|(color, kind)| {
            usize::try_from(position.pieces(color, kind).count()).expect(\"piece count fits usize\")
        })
        .sum();
    (men.saturating_sub(2) / 4).min(OUTPUT_BUCKETS - 1)
}
""",
    """fn output_bucket(position: &Position) -> usize {
    let men = usize::try_from(position.occupied().count()).expect(\"piece count fits usize\");
    (men.saturating_sub(2) / 4).min(OUTPUT_BUCKETS - 1)
}
""",
    "single-popcount output bucket",
)

path.write_text(text)
print("applied safe V15 perseverance v2 hot-path optimisations")
