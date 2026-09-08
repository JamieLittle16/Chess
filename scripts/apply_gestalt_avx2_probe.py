#!/usr/bin/env python3
"""Apply research-only AVX2/fused kernels to the certified gestalt evaluator.

The committed scalar implementation remains the correctness oracle. Qualification applies this patch
on x86-64 runners, requires the ordinary evaluator tests and the independent v13 score oracle to stay
exact, then measures search-node wall time before any equal-time strength claim.
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

    old_apply = '''    fn apply_feature(
        &self,
        values: &mut [i16; HIDDEN],
        bucket: u8,
        feature: u16,
        direction: Direction,
    ) {
        let start = (usize::from(bucket) * INPUTS + usize::from(feature)) * HIDDEN;
        let row = &self.feature_weights[start..start + HIDDEN];
        match direction {
            Direction::Add => {
                for (value, weight) in values.iter_mut().zip(row) {
                    *value = value.wrapping_add(*weight);
                }
            }
            Direction::Subtract => {
                for (value, weight) in values.iter_mut().zip(row) {
                    *value = value.wrapping_sub(*weight);
                }
            }
        }
    }
'''
    new_apply = '''    fn apply_feature(
        &self,
        values: &mut [i16; HIDDEN],
        bucket: u8,
        feature: u16,
        direction: Direction,
    ) {
        let start = (usize::from(bucket) * INPUTS + usize::from(feature)) * HIDDEN;
        let row = &self.feature_weights[start..start + HIDDEN];
        #[cfg(target_arch = "x86_64")]
        if std::arch::is_x86_feature_detected!("avx2") {
            // SAFETY: AVX2 was detected at runtime; both slices contain exactly HIDDEN i16 lanes.
            unsafe { apply_feature_avx2(values, row, direction) };
            return;
        }
        apply_feature_scalar(values, row, direction);
    }

    fn apply_delta(
        &self,
        values: &mut [i16; HIDDEN],
        bucket: u8,
        delta: FeatureDelta,
        reverse: bool,
    ) {
        #[cfg(target_arch = "x86_64")]
        if std::arch::is_x86_feature_detected!("avx2") {
            // SAFETY: AVX2 was detected at runtime. Feature indices were produced by the certified
            // mapper and every selected row has HIDDEN i16 lanes.
            unsafe { self.apply_delta_avx2(values, bucket, delta, reverse) };
            return;
        }

        if reverse {
            for &feature in delta.added() {
                self.apply_feature(values, bucket, feature, Direction::Subtract);
            }
            for &feature in delta.removed() {
                self.apply_feature(values, bucket, feature, Direction::Add);
            }
        } else {
            for &feature in delta.removed() {
                self.apply_feature(values, bucket, feature, Direction::Subtract);
            }
            for &feature in delta.added() {
                self.apply_feature(values, bucket, feature, Direction::Add);
            }
        }
    }

    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    unsafe fn apply_delta_avx2(
        &self,
        values: &mut [i16; HIDDEN],
        bucket: u8,
        delta: FeatureDelta,
        reverse: bool,
    ) {
        use std::arch::x86_64::{
            __m256i, _mm256_add_epi16, _mm256_loadu_si256, _mm256_storeu_si256,
            _mm256_sub_epi16,
        };

        let bucket_base = usize::from(bucket) * INPUTS * HIDDEN;
        let mut offset = 0usize;
        while offset < HIDDEN {
            // SAFETY: offset advances by 16 and HIDDEN is a multiple of 16.
            let mut value = unsafe {
                _mm256_loadu_si256(values.as_ptr().add(offset).cast::<__m256i>())
            };

            for &feature in delta.removed() {
                let start = bucket_base + usize::from(feature) * HIDDEN + offset;
                // SAFETY: certified feature indices select a complete HIDDEN-lane row.
                let weight = unsafe {
                    _mm256_loadu_si256(self.feature_weights.as_ptr().add(start).cast::<__m256i>())
                };
                value = if reverse {
                    _mm256_add_epi16(value, weight)
                } else {
                    _mm256_sub_epi16(value, weight)
                };
            }
            for &feature in delta.added() {
                let start = bucket_base + usize::from(feature) * HIDDEN + offset;
                // SAFETY: certified feature indices select a complete HIDDEN-lane row.
                let weight = unsafe {
                    _mm256_loadu_si256(self.feature_weights.as_ptr().add(start).cast::<__m256i>())
                };
                value = if reverse {
                    _mm256_sub_epi16(value, weight)
                } else {
                    _mm256_add_epi16(value, weight)
                };
            }

            // SAFETY: values has HIDDEN lanes and offset is in-bounds for a 16-lane store.
            unsafe {
                _mm256_storeu_si256(values.as_mut_ptr().add(offset).cast::<__m256i>(), value);
            }
            offset += 16;
        }
    }
'''
    text = replace_exact(text, old_apply, new_apply, label="feature/delta kernels")

    old_score = '''        let mut output = 0_i64;
        for (index, &value) in us.iter().enumerate() {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[index]);
        }
        for (index, &value) in them.iter().enumerate() {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[HIDDEN + index]);
        }
'''
    new_score = '''        let mut output = screlu_dot(us, &self.output_weights[..HIDDEN]);
        output += screlu_dot(them, &self.output_weights[HIDDEN..]);
'''
    text = replace_exact(text, old_score, new_score, label="SCReLU output dot")

    old_delta = '''        PerspectiveUpdate::Delta(delta) => {
            if reverse {
                for &feature in delta.added() {
                    network.apply_feature(
                        &mut accumulator.values,
                        accumulator.frame.bucket,
                        feature,
                        Direction::Subtract,
                    );
                }
                for &feature in delta.removed() {
                    network.apply_feature(
                        &mut accumulator.values,
                        accumulator.frame.bucket,
                        feature,
                        Direction::Add,
                    );
                }
            } else {
                for &feature in delta.removed() {
                    network.apply_feature(
                        &mut accumulator.values,
                        accumulator.frame.bucket,
                        feature,
                        Direction::Subtract,
                    );
                }
                for &feature in delta.added() {
                    network.apply_feature(
                        &mut accumulator.values,
                        accumulator.frame.bucket,
                        feature,
                        Direction::Add,
                    );
                }
            }
        }
'''
    new_delta = '''        PerspectiveUpdate::Delta(delta) => {
            network.apply_delta(
                &mut accumulator.values,
                accumulator.frame.bucket,
                delta,
                reverse,
            );
        }
'''
    text = replace_exact(text, old_delta, new_delta, label="fused delta application")

    marker = '''/// Perspective coordinate frame. `bucket` selects physical weights; `mirror_files` distinguishes the
'''
    helpers = '''fn apply_feature_scalar(
    values: &mut [i16; HIDDEN],
    row: &[i16],
    direction: Direction,
) {
    match direction {
        Direction::Add => {
            for (value, weight) in values.iter_mut().zip(row) {
                *value = value.wrapping_add(*weight);
            }
        }
        Direction::Subtract => {
            for (value, weight) in values.iter_mut().zip(row) {
                *value = value.wrapping_sub(*weight);
            }
        }
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn apply_feature_avx2(
    values: &mut [i16; HIDDEN],
    row: &[i16],
    direction: Direction,
) {
    use std::arch::x86_64::{
        __m256i, _mm256_add_epi16, _mm256_loadu_si256, _mm256_storeu_si256, _mm256_sub_epi16,
    };

    let mut offset = 0usize;
    while offset < HIDDEN {
        // SAFETY: offset advances by 16 and both slices have HIDDEN lanes.
        let (value, weight) = unsafe {
            (
                _mm256_loadu_si256(values.as_ptr().add(offset).cast::<__m256i>()),
                _mm256_loadu_si256(row.as_ptr().add(offset).cast::<__m256i>()),
            )
        };
        let result = match direction {
            Direction::Add => _mm256_add_epi16(value, weight),
            Direction::Subtract => _mm256_sub_epi16(value, weight),
        };
        // SAFETY: offset is in-bounds for a 16-lane store.
        unsafe {
            _mm256_storeu_si256(values.as_mut_ptr().add(offset).cast::<__m256i>(), result);
        }
        offset += 16;
    }
}

fn screlu_dot(values: &[i16; HIDDEN], weights: &[i16]) -> i64 {
    debug_assert_eq!(weights.len(), HIDDEN);
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        // SAFETY: AVX2 was detected at runtime and both inputs have HIDDEN lanes.
        return unsafe { screlu_dot_avx2(values, weights) };
    }
    screlu_dot_scalar(values, weights)
}

fn screlu_dot_scalar(values: &[i16; HIDDEN], weights: &[i16]) -> i64 {
    values
        .iter()
        .zip(weights)
        .map(|(&value, &weight)| {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            clipped * clipped * i64::from(weight)
        })
        .sum()
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn screlu_dot_avx2(values: &[i16; HIDDEN], weights: &[i16]) -> i64 {
    use std::arch::x86_64::{
        __m128i, __m256i, _mm_loadu_si128, _mm256_add_epi64, _mm256_castsi256_si128,
        _mm256_cvtepi16_epi32, _mm256_cvtepi32_epi64, _mm256_extracti128_si256,
        _mm256_max_epi32, _mm256_min_epi32, _mm256_mullo_epi32, _mm256_set1_epi32,
        _mm256_setzero_si256, _mm256_storeu_si256,
    };

    let zero = _mm256_setzero_si256();
    let ceiling = _mm256_set1_epi32(QA);
    let mut sum = _mm256_setzero_si256();
    let mut offset = 0usize;
    while offset < HIDDEN {
        // SAFETY: offset advances by eight and both inputs have HIDDEN lanes.
        let (raw_value, raw_weight) = unsafe {
            (
                _mm_loadu_si128(values.as_ptr().add(offset).cast::<__m128i>()),
                _mm_loadu_si128(weights.as_ptr().add(offset).cast::<__m128i>()),
            )
        };
        let value = _mm256_cvtepi16_epi32(raw_value);
        let value = _mm256_min_epi32(_mm256_max_epi32(value, zero), ceiling);
        let squared = _mm256_mullo_epi32(value, value);
        let weight = _mm256_cvtepi16_epi32(raw_weight);
        // 255^2 * i16::MIN/MAX fits in signed i32, so widening after the product is exact.
        let product = _mm256_mullo_epi32(squared, weight);
        let low = _mm256_castsi256_si128(product);
        let high = _mm256_extracti128_si256::<1>(product);
        sum = _mm256_add_epi64(sum, _mm256_cvtepi32_epi64(low));
        sum = _mm256_add_epi64(sum, _mm256_cvtepi32_epi64(high));
        offset += 8;
    }

    let mut lanes = [0_i64; 4];
    // SAFETY: lanes is exactly one 256-bit vector.
    unsafe {
        _mm256_storeu_si256(lanes.as_mut_ptr().cast::<__m256i>(), sum);
    }
    lanes.into_iter().sum()
}

'''
    if text.count(marker) != 1:
        raise PatchError(f"helper insertion marker: expected one occurrence, found {text.count(marker)}")
    text = text.replace(marker, helpers + marker, 1)

    path.write_text(text, encoding="utf-8")
    print("applied AVX2 SCReLU + fused accumulator kernels; scalar fallback retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
