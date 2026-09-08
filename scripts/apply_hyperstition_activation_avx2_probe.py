#!/usr/bin/env python3
"""Vectorise Hyperstition pairwise FT activation with safe_arch AVX2.

This is deliberately an experiment patcher. It changes no network, search, accumulator, or floating
point dense-layer semantics. The candidate replaces only the 2x1024 scalar pairwise activation loop
with the exact AVX2 signed-high-multiply/unsigned-pack sequence used by the pinned Viridithas
reference, expressed through safe_arch so the repository-wide unsafe-code prohibition remains intact.
"""

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
        """        let mut ft = [0_u8; HIDDEN];
        activate_pairwise_simd_quantized(us, &mut ft[..HIDDEN / 2]);
        activate_pairwise_simd_quantized(them, &mut ft[HIDDEN / 2..]);

        let l1_weight_base = bucket * HIDDEN * L2;
""",
        """        let mut ft = [0_u8; HIDDEN];
        #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]
        {
            activate_pairwise_safe_avx2(us, &mut ft[..HIDDEN / 2]);
            activate_pairwise_safe_avx2(them, &mut ft[HIDDEN / 2..]);
        }
        #[cfg(not(all(target_arch = \"x86_64\", target_feature = \"avx2\")))]
        {
            activate_pairwise_simd_quantized(us, &mut ft[..HIDDEN / 2]);
            activate_pairwise_simd_quantized(them, &mut ft[HIDDEN / 2..]);
        }

        let l1_weight_base = bucket * HIDDEN * L2;
""",
        count=1,
        label="activation dispatch",
    )

    marker = """fn activate_pairwise_simd_quantized(accumulator: &[i16; HIDDEN], output: &mut [u8]) {
    debug_assert_eq!(output.len(), HIDDEN / 2);
    for index in 0..HIDDEN / 2 {
        let left = i32::from(accumulator[index]).clamp(0, QA);
        let right = i32::from(accumulator[HIDDEN / 2 + index]).clamp(0, QA);
        let product = (left * right) >> FT_SHIFT;
        output[index] = product.clamp(0, i32::from(u8::MAX)) as u8;
    }
}

"""
    replacement = marker + """#[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]
fn activate_pairwise_safe_avx2(accumulator: &[i16; HIDDEN], output: &mut [u8]) {
    use safe_arch::{
        m256i, max_i16_m256i, min_i16_m256i, mul_i16_keep_high_m256i,
        pack_i16_to_u8_m256i, shl_imm_u16_m256i, shuffle_ai_i64_all_m256i,
    };

    debug_assert_eq!(output.len(), HIDDEN / 2);
    let zero = m256i::from([0_i16; 16]);
    let qa = m256i::from([QA as i16; 16]);

    // Two 16-lane vectors become one sequential 32-byte output vector. AVX2 pack instructions
    // operate independently on 128-bit halves, yielding lanes [a_lo, b_lo, a_hi, b_hi]; the
    // 64-bit permutation 0xD8 restores [a_lo, a_hi, b_lo, b_hi].
    for index in (0..HIDDEN / 2).step_by(32) {
        let left_a = m256i::from(
            <[i16; 16]>::try_from(&accumulator[index..index + 16])
                .expect("sixteen FT left lanes"),
        );
        let left_b = m256i::from(
            <[i16; 16]>::try_from(&accumulator[index + 16..index + 32])
                .expect("sixteen FT left lanes"),
        );
        let right_base = HIDDEN / 2 + index;
        let right_a = m256i::from(
            <[i16; 16]>::try_from(&accumulator[right_base..right_base + 16])
                .expect("sixteen FT right lanes"),
        );
        let right_b = m256i::from(
            <[i16; 16]>::try_from(&accumulator[right_base + 16..right_base + 32])
                .expect("sixteen FT right lanes"),
        );

        let left_a = min_i16_m256i(max_i16_m256i(left_a, zero), qa);
        let left_b = min_i16_m256i(max_i16_m256i(left_b, zero), qa);
        let right_a = min_i16_m256i(max_i16_m256i(right_a, zero), qa);
        let right_b = min_i16_m256i(max_i16_m256i(right_b, zero), qa);

        let product_a = mul_i16_keep_high_m256i(shl_imm_u16_m256i::<6>(left_a), right_a);
        let product_b = mul_i16_keep_high_m256i(shl_imm_u16_m256i::<6>(left_b), right_b);
        let packed = pack_i16_to_u8_m256i(product_a, product_b);
        let sequential = shuffle_ai_i64_all_m256i::<0xD8>(packed);
        let bytes: [u8; 32] = sequential.into();
        output[index..index + 32].copy_from_slice(&bytes);
    }
}

"""
    text = replace_exact(text, marker, replacement, count=1, label="AVX2 activation implementation")

    test_marker = """    #[test]
    fn simd_pairwise_activation_matches_reference_scaling() {
        let mut accumulator = [0_i16; HIDDEN];
        accumulator[0] = 255;
        accumulator[HIDDEN / 2] = 255;
        accumulator[1] = 128;
        accumulator[HIDDEN / 2 + 1] = 128;
        let mut output = [0_u8; HIDDEN / 2];
        activate_pairwise_simd_quantized(&accumulator, &mut output);
        assert_eq!(output[0], 63);
        assert_eq!(output[1], 16);
    }

"""
    test_replacement = test_marker + """    #[cfg(all(target_arch = \"x86_64\", target_feature = \"avx2\"))]
    #[test]
    fn safe_avx2_pairwise_activation_is_bit_exact_to_scalar_oracle() {
        let mut accumulator = [0_i16; HIDDEN];
        for (index, value) in accumulator.iter_mut().enumerate() {
            let mixed = ((index * 197 + 31) % 721) as i16 - 233;
            *value = mixed;
        }
        // Pin boundary and saturation cases explicitly as well as the broad deterministic sample.
        accumulator[0] = i16::MIN;
        accumulator[1] = -1;
        accumulator[2] = 0;
        accumulator[3] = 1;
        accumulator[4] = 254;
        accumulator[5] = 255;
        accumulator[6] = 256;
        accumulator[7] = i16::MAX;
        accumulator[HIDDEN / 2] = 255;
        accumulator[HIDDEN / 2 + 1] = 255;
        accumulator[HIDDEN / 2 + 2] = 255;
        accumulator[HIDDEN / 2 + 3] = 255;
        accumulator[HIDDEN / 2 + 4] = 255;
        accumulator[HIDDEN / 2 + 5] = 255;
        accumulator[HIDDEN / 2 + 6] = 255;
        accumulator[HIDDEN / 2 + 7] = 255;

        let mut scalar = [0_u8; HIDDEN / 2];
        let mut avx2 = [0_u8; HIDDEN / 2];
        activate_pairwise_simd_quantized(&accumulator, &mut scalar);
        activate_pairwise_safe_avx2(&accumulator, &mut avx2);
        assert_eq!(avx2, scalar);
    }

"""
    text = replace_exact(text, test_marker, test_replacement, count=1, label="AVX2 activation parity test")

    path.write_text(text, encoding="utf-8")
    print("applied safe AVX2 Hyperstition pairwise activation candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
