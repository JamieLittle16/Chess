#!/usr/bin/env python3
"""Apply a parity-preserving sparse L1 inference probe to Hyperstition.

The v92 file already stores L1 weights as [4-input chunk][output][lane].  Production scalar
inference currently canonicalises those bytes into dense output-major rows, then visits all 2048
inputs for every one of 16 outputs.  This experiment retains the serialized L1 matrix as a second,
tiny (~256 KiB) view and skips four-input chunks whose activated bytes are all zero.

Arithmetic is deliberately scalar and in the same i32 accumulation domain as the certified oracle.
This isolates the value of sparsity/native layout before introducing any target-specific SIMD.
"""

from __future__ import annotations

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int = 1, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new, count)


def main() -> int:
    path = Path("crates/chess-eval/src/hyperstition.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """    /// Canonical output-major rows, converted from Viridithas's four-byte SIMD interleave at load.
    l1_weights: Box<[i8]>,
    l1_bias: Box<[f32]>,""",
        """    /// Canonical output-major rows retained as the scalar parity oracle.
    l1_weights: Box<[i8]>,
    /// Native v92 `[four-input chunk][output][lane]` L1 storage used by the sparse hot path.
    l1_weights_simd: Box<[i8]>,
    l1_bias: Box<[f32]>,""",
        label="Network L1 fields",
    )

    text = replace_exact(
        text,
        """        let serialized_l1 = read_i8s(bytes, &mut cursor, L1_WEIGHTS)?;
        let l1_weights = canonicalize_simd_l1(&serialized_l1);
        let l1_bias = read_f32s(bytes, &mut cursor, L1_BIAS)?;""",
        """        let serialized_l1 = read_i8s(bytes, &mut cursor, L1_WEIGHTS)?;
        let l1_weights = canonicalize_simd_l1(&serialized_l1);
        let l1_weights_simd = serialized_l1;
        let l1_bias = read_f32s(bytes, &mut cursor, L1_BIAS)?;""",
        label="retain serialized L1",
    )

    text = replace_exact(
        text,
        """            l1_weights,
            l1_bias,""",
        """            l1_weights,
            l1_weights_simd,
            l1_bias,""",
        label="Network construction",
    )

    dense = """        let l1_weight_base = bucket * HIDDEN * L2;
        let l1_bias_base = bucket * L2;
        let mut l1 = [0_f32; L2];
        for (output, output_value) in l1.iter_mut().enumerate() {
            let row = &self.l1_weights
                [l1_weight_base + output * HIDDEN..l1_weight_base + (output + 1) * HIDDEN];
            let mut sum = 0_i32;
            for (&input, &weight) in ft.iter().zip(row) {
                sum += i32::from(input) * i32::from(weight);
            }
            let value = (sum as f32).mul_add(L1_MUL, self.l1_bias[l1_bias_base + output]);
            let clipped = value.clamp(0.0, 1.0);
            *output_value = clipped * clipped;
        }
"""
    sparse = """        let l1_weight_base = bucket * HIDDEN * L2;
        let l1_bias_base = bucket * L2;
        let mut l1_sums = [0_i32; L2];
        for chunk in 0..HIDDEN / L1_INPUT_CHUNK {
            let input_base = chunk * L1_INPUT_CHUNK;
            let inputs = &ft[input_base..input_base + L1_INPUT_CHUNK];
            if inputs.iter().all(|&input| input == 0) {
                continue;
            }
            let weight_chunk_base =
                l1_weight_base + chunk * L1_INPUT_CHUNK * L2;
            for (output, sum) in l1_sums.iter_mut().enumerate() {
                let weights = &self.l1_weights_simd
                    [weight_chunk_base + output * L1_INPUT_CHUNK
                        ..weight_chunk_base + (output + 1) * L1_INPUT_CHUNK];
                for lane in 0..L1_INPUT_CHUNK {
                    *sum += i32::from(inputs[lane]) * i32::from(weights[lane]);
                }
            }
        }
        let mut l1 = [0_f32; L2];
        for (output, output_value) in l1.iter_mut().enumerate() {
            let value = (l1_sums[output] as f32)
                .mul_add(L1_MUL, self.l1_bias[l1_bias_base + output]);
            let clipped = value.clamp(0.0, 1.0);
            *output_value = clipped * clipped;
        }
"""
    text = replace_exact(text, dense, sparse, label="dense L1 hot loop")

    # The canonical copy remains intentionally live as a loader/parity oracle during this first
    # experiment.  Assert both views have the expected size so a malformed load cannot slip through.
    marker = """    #[test]
    fn simd_layout_canonicalizers_preserve_known_coordinates() {
"""
    text = replace_exact(
        text,
        marker,
        """    #[test]
    fn sparse_l1_native_view_has_exact_serialized_extent() {
        assert_eq!(L1_WEIGHTS, OUTPUT_BUCKETS * HIDDEN * L2);
    }

""" + marker,
        label="sparse L1 shape test",
    )

    path.write_text(text, encoding="utf-8")
    print("applied scalar sparse Hyperstition L1 probe using native 4-byte chunk layout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
