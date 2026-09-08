#!/usr/bin/env python3
"""Apply a safe_arch AVX2 L1 inference probe to Hyperstition.

On AVX2 builds this keeps the v92 native four-input L1 layout and consumes it with the same
`maddubs` + `maddwd` arithmetic used by Viridithas v14. Non-AVX2 builds retain the already-certified
canonical scalar layout. The two representations are cfg-exclusive, so production memory does not
pay for a duplicate matrix. `safe_arch` exposes the packed operations without weakening the
workspace-wide `unsafe_code = "forbid"` contract.
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


def patch_manifest() -> None:
    path = Path("crates/chess-eval/Cargo.toml")
    text = path.read_text(encoding="utf-8")
    if 'safe_arch = "=1.2.0"' in text:
        return
    text = replace_exact(
        text,
        """[dependencies]\nchess-core = { path = \"../chess-core\" }\n""",
        """[dependencies]\nchess-core = { path = \"../chess-core\" }\nsafe_arch = \"=1.2.0\"\n""",
        label="chess-eval dependencies",
    )
    path.write_text(text, encoding="utf-8")


def patch_runtime() -> None:
    path = Path("crates/chess-eval/src/hyperstition.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """    /// Canonical output-major rows, converted from Viridithas's four-byte SIMD interleave at load.\n    l1_weights: Box<[i8]>,\n    l1_bias: Box<[f32]>,""",
        """    /// Canonical output-major rows used by the portable scalar backend.\n    #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\")))]\n    l1_weights: Box<[i8]>,\n    /// Native v92 `[four-input chunk][output][lane]` bytes consumed directly by AVX2.\n    #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]\n    l1_weights_simd: Box<[i8]>,\n    l1_bias: Box<[f32]>,""",
        label="Network L1 fields",
    )

    text = replace_exact(
        text,
        """        let serialized_l1 = read_i8s(bytes, &mut cursor, L1_WEIGHTS)?;\n        let l1_weights = canonicalize_simd_l1(&serialized_l1);\n        let l1_bias = read_f32s(bytes, &mut cursor, L1_BIAS)?;""",
        """        let serialized_l1 = read_i8s(bytes, &mut cursor, L1_WEIGHTS)?;\n        #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\")))]\n        let l1_weights = canonicalize_simd_l1(&serialized_l1);\n        #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]\n        let l1_weights_simd = serialized_l1;\n        let l1_bias = read_f32s(bytes, &mut cursor, L1_BIAS)?;""",
        label="select L1 representation",
    )

    text = replace_exact(
        text,
        """            l1_weights,\n            l1_bias,""",
        """            #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\")))]\n            l1_weights,\n            #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]\n            l1_weights_simd,\n            l1_bias,""",
        label="Network construction",
    )

    dense = """        let l1_weight_base = bucket * HIDDEN * L2;\n        let l1_bias_base = bucket * L2;\n        let mut l1 = [0_f32; L2];\n        for (output, output_value) in l1.iter_mut().enumerate() {\n            let row = &self.l1_weights\n                [l1_weight_base + output * HIDDEN..l1_weight_base + (output + 1) * HIDDEN];\n            let mut sum = 0_i32;\n            for (&input, &weight) in ft.iter().zip(row) {\n                sum += i32::from(input) * i32::from(weight);\n            }\n            let value = (sum as f32).mul_add(L1_MUL, self.l1_bias[l1_bias_base + output]);\n            let clipped = value.clamp(0.0, 1.0);\n            *output_value = clipped * clipped;\n        }\n"""

    dispatched = """        let l1_weight_base = bucket * HIDDEN * L2;\n        let l1_bias_base = bucket * L2;\n        #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]\n        let l1 = propagate_l1_safe_avx2(\n            &ft,\n            &self.l1_weights_simd[l1_weight_base..l1_weight_base + HIDDEN * L2],\n            &self.l1_bias[l1_bias_base..l1_bias_base + L2],\n        );\n        #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\")))]\n        let l1 = {\n            let mut values = [0_f32; L2];\n            for (output, output_value) in values.iter_mut().enumerate() {\n                let row = &self.l1_weights\n                    [l1_weight_base + output * HIDDEN..l1_weight_base + (output + 1) * HIDDEN];\n                let mut sum = 0_i32;\n                for (&input, &weight) in ft.iter().zip(row) {\n                    sum += i32::from(input) * i32::from(weight);\n                }\n                let value =\n                    (sum as f32).mul_add(L1_MUL, self.l1_bias[l1_bias_base + output]);\n                let clipped = value.clamp(0.0, 1.0);\n                *output_value = clipped * clipped;\n            }\n            values\n        };\n"""
    text = replace_exact(text, dense, dispatched, label="L1 dispatch")

    marker = """fn output_bucket(position: &Position) -> usize {\n"""
    helper = """#[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]\nfn propagate_l1_safe_avx2(ft: &[u8; HIDDEN], weights: &[i8], biases: &[f32]) -> [f32; L2] {\n    use safe_arch::{\n        add_i32_m256i, m256i, mul_i16_horizontal_add_m256i,\n        mul_u8i8_add_horizontal_saturating_m256i,\n    };\n\n    debug_assert_eq!(weights.len(), HIDDEN * L2);\n    debug_assert_eq!(biases.len(), L2);\n\n    let zero = m256i::from([0_i32; 8]);\n    let ones = m256i::from([1_i16; 16]);\n    let mut sums_lo = zero;\n    let mut sums_hi = zero;\n\n    for chunk in 0..HIDDEN / L1_INPUT_CHUNK {\n        let input_base = chunk * L1_INPUT_CHUNK;\n        let input_word = i32::from_le_bytes(\n            ft[input_base..input_base + L1_INPUT_CHUNK]\n                .try_into()\n                .expect(\"four-byte FT chunk\"),\n        );\n        let input = m256i::from([input_word; 8]);\n        let weight_base = chunk * L1_INPUT_CHUNK * L2;\n        let weights_lo = m256i::from(\n            <[i8; 32]>::try_from(&weights[weight_base..weight_base + 32])\n                .expect(\"eight four-byte L1 rows\"),\n        );\n        let weights_hi = m256i::from(\n            <[i8; 32]>::try_from(&weights[weight_base + 32..weight_base + 64])\n                .expect(\"eight four-byte L1 rows\"),\n        );\n\n        let partial_lo = mul_i16_horizontal_add_m256i(\n            mul_u8i8_add_horizontal_saturating_m256i(input, weights_lo),\n            ones,\n        );\n        let partial_hi = mul_i16_horizontal_add_m256i(\n            mul_u8i8_add_horizontal_saturating_m256i(input, weights_hi),\n            ones,\n        );\n        sums_lo = add_i32_m256i(sums_lo, partial_lo);\n        sums_hi = add_i32_m256i(sums_hi, partial_hi);\n    }\n\n    let sums_lo: [i32; 8] = sums_lo.into();\n    let sums_hi: [i32; 8] = sums_hi.into();\n    let mut output = [0_f32; L2];\n    for index in 0..8 {\n        let value = (sums_lo[index] as f32).mul_add(L1_MUL, biases[index]);\n        let clipped = value.clamp(0.0, 1.0);\n        output[index] = clipped * clipped;\n    }\n    for index in 0..8 {\n        let value = (sums_hi[index] as f32).mul_add(L1_MUL, biases[index + 8]);\n        let clipped = value.clamp(0.0, 1.0);\n        output[index + 8] = clipped * clipped;\n    }\n    output\n}\n\n"""
    text = replace_exact(text, marker, helper + marker, label="AVX2 L1 helper")

    test_marker = """    #[test]\n    fn simd_layout_canonicalizers_preserve_known_coordinates() {\n"""
    test = """    #[test]\n    fn native_l1_layout_is_two_avx2_vectors_per_four_input_chunk() {\n        assert_eq!(L1_INPUT_CHUNK, 4);\n        assert_eq!(L2, 16);\n        assert_eq!(L1_INPUT_CHUNK * L2, 64);\n    }\n\n"""
    text = replace_exact(text, test_marker, test + test_marker, label="AVX2 layout invariant test")

    path.write_text(text, encoding="utf-8")


def main() -> int:
    patch_manifest()
    patch_runtime()
    print("applied cfg-exact safe_arch AVX2 Hyperstition L1 probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
