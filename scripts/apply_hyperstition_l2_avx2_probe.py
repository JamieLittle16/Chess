#!/usr/bin/env python3
"""Vectorise Hyperstition L2 across outputs while preserving scalar FMA order per neuron."""

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new)


def main() -> int:
    path = Path("crates/chess-eval/src/hyperstition.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """    /// Canonical output-major rows, converted from Viridithas's SIMD input-major storage at load.
    l2_weights: Box<[f32]>,
""",
        """    /// Canonical output-major rows used by the portable scalar backend.
    #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\")))]
    l2_weights: Box<[f32]>,
    /// Native v92 input-major L2 rows. This layout lets AVX2 update 32 outputs in parallel while
    /// preserving each neuron's scalar input accumulation order exactly.
    #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\"))]
    l2_weights_simd: Box<[f32]>,
""",
        count=1,
        label="L2 network fields",
    )

    text = replace_exact(
        text,
        """        let serialized_l2 = read_f32s(bytes, &mut cursor, L2_WEIGHTS)?;
        let l2_weights = canonicalize_simd_l2(&serialized_l2);
        let l2_bias = read_f32s(bytes, &mut cursor, L2_BIAS)?;
""",
        """        let serialized_l2 = read_f32s(bytes, &mut cursor, L2_WEIGHTS)?;
        #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\")))]
        let l2_weights = canonicalize_simd_l2(&serialized_l2);
        #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\"))]
        let l2_weights_simd = serialized_l2;
        let l2_bias = read_f32s(bytes, &mut cursor, L2_BIAS)?;
""",
        count=1,
        label="L2 loader",
    )

    text = replace_exact(
        text,
        """            l1_bias,
            l2_weights,
            l2_bias,
""",
        """            l1_bias,
            #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\")))]
            l2_weights,
            #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\"))]
            l2_weights_simd,
            l2_bias,
""",
        count=1,
        label="L2 network construction",
    )

    old_l2 = """        let l2_weight_base = bucket * L2 * L3;
        let l2_bias_base = bucket * L3;
        let mut l2 = [0_f32; L3];
        for (output, output_value) in l2.iter_mut().enumerate() {
            let row =
                &self.l2_weights[l2_weight_base + output * L2..l2_weight_base + (output + 1) * L2];
            let mut value = self.l2_bias[l2_bias_base + output];
            for (&input, &weight) in l1.iter().zip(row) {
                value = input.mul_add(weight, value);
            }
            let clipped = value.clamp(0.0, 1.0);
            *output_value = clipped * clipped;
        }

"""
    new_l2 = """        let l2_weight_base = bucket * L2 * L3;
        let l2_bias_base = bucket * L3;
        #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\"))]
        let l2 = propagate_l2_safe_avx2(
            &l1,
            &self.l2_weights_simd[l2_weight_base..l2_weight_base + L2 * L3],
            &self.l2_bias[l2_bias_base..l2_bias_base + L3],
        );
        #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\")))]
        let l2 = {
            let mut values = [0_f32; L3];
            for (output, output_value) in values.iter_mut().enumerate() {
                let row = &self.l2_weights
                    [l2_weight_base + output * L2..l2_weight_base + (output + 1) * L2];
                let mut value = self.l2_bias[l2_bias_base + output];
                for (&input, &weight) in l1.iter().zip(row) {
                    value = input.mul_add(weight, value);
                }
                let clipped = value.clamp(0.0, 1.0);
                *output_value = clipped * clipped;
            }
            values
        };

"""
    text = replace_exact(text, old_l2, new_l2, count=1, label="L2 propagation dispatch")

    l1_end = """    output
}

fn output_bucket(position: &Position) -> usize {
"""
    l2_fn = """    output
}

#[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\"))]
fn propagate_l2_safe_avx2(l1: &[f32; L2], weights: &[f32], biases: &[f32]) -> [f32; L3] {
    use safe_arch::{fused_mul_add_m256, m256, max_m256, min_m256, mul_m256};

    debug_assert_eq!(weights.len(), L2 * L3);
    debug_assert_eq!(biases.len(), L3);

    let mut acc0 = m256::from(<[f32; 8]>::try_from(&biases[0..8]).expect("eight L2 biases"));
    let mut acc1 = m256::from(<[f32; 8]>::try_from(&biases[8..16]).expect("eight L2 biases"));
    let mut acc2 = m256::from(<[f32; 8]>::try_from(&biases[16..24]).expect("eight L2 biases"));
    let mut acc3 = m256::from(<[f32; 8]>::try_from(&biases[24..32]).expect("eight L2 biases"));

    for (input_index, &input) in l1.iter().enumerate() {
        let input = m256::from([input; 8]);
        let base = input_index * L3;
        let w0 = m256::from(<[f32; 8]>::try_from(&weights[base..base + 8]).expect("eight L2 weights"));
        let w1 = m256::from(<[f32; 8]>::try_from(&weights[base + 8..base + 16]).expect("eight L2 weights"));
        let w2 = m256::from(<[f32; 8]>::try_from(&weights[base + 16..base + 24]).expect("eight L2 weights"));
        let w3 = m256::from(<[f32; 8]>::try_from(&weights[base + 24..base + 32]).expect("eight L2 weights"));
        acc0 = fused_mul_add_m256(input, w0, acc0);
        acc1 = fused_mul_add_m256(input, w1, acc1);
        acc2 = fused_mul_add_m256(input, w2, acc2);
        acc3 = fused_mul_add_m256(input, w3, acc3);
    }

    let zero = m256::from([0.0; 8]);
    let one = m256::from([1.0; 8]);
    let activate = |value: m256| {
        let clipped = min_m256(max_m256(value, zero), one);
        mul_m256(clipped, clipped)
    };
    let a0: [f32; 8] = activate(acc0).into();
    let a1: [f32; 8] = activate(acc1).into();
    let a2: [f32; 8] = activate(acc2).into();
    let a3: [f32; 8] = activate(acc3).into();
    let mut output = [0_f32; L3];
    output[0..8].copy_from_slice(&a0);
    output[8..16].copy_from_slice(&a1);
    output[16..24].copy_from_slice(&a2);
    output[24..32].copy_from_slice(&a3);
    output
}

fn output_bucket(position: &Position) -> usize {
"""
    text = replace_exact(text, l1_end, l2_fn, count=1, label="safe AVX2 L2 function")

    text = replace_exact(
        text,
        """/// Convert Viridithas's SIMD L2 serialization from input-major to scalar output-major rows.
fn canonicalize_simd_l2(serialized: &[f32]) -> Box<[f32]> {
""",
        """/// Convert Viridithas's SIMD L2 serialization from input-major to scalar output-major rows.
#[cfg(any(test, not(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\"))))]
fn canonicalize_simd_l2(serialized: &[f32]) -> Box<[f32]> {
""",
        count=1,
        label="portable L2 canonicalizer cfg",
    )

    test_marker = """    #[test]
    fn prepared_update_remains_small() {
"""
    test = """    #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\", target_feature = \"fma\"))]
    #[test]
    fn safe_avx2_l2_is_bit_exact_to_scalar_input_order() {
        let mut l1 = [0_f32; L2];
        for (index, value) in l1.iter_mut().enumerate() {
            *value = ((index as f32) - 7.0) * 0.03125 + 0.4;
        }
        let mut weights = [0_f32; L2 * L3];
        for input in 0..L2 {
            for output in 0..L3 {
                weights[input * L3 + output] = (((input * 37 + output * 13) % 97) as f32 - 48.0) / 211.0;
            }
        }
        let mut biases = [0_f32; L3];
        for (index, bias) in biases.iter_mut().enumerate() {
            *bias = (index as f32 - 15.0) / 73.0;
        }

        let simd = propagate_l2_safe_avx2(&l1, &weights, &biases);
        let mut scalar = [0_f32; L3];
        for output in 0..L3 {
            let mut value = biases[output];
            for input in 0..L2 {
                value = l1[input].mul_add(weights[input * L3 + output], value);
            }
            let clipped = value.clamp(0.0, 1.0);
            scalar[output] = clipped * clipped;
        }
        for index in 0..L3 {
            assert_eq!(simd[index].to_bits(), scalar[index].to_bits(), "L2 lane {index}");
        }
    }

    #[test]
    fn prepared_update_remains_small() {
"""
    text = replace_exact(text, test_marker, test, count=1, label="L2 bit-exact unit test")

    path.write_text(text, encoding="utf-8")
    print("applied order-preserving safe AVX2 Hyperstition L2 candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
