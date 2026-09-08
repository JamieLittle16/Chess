#!/usr/bin/env python3
"""Apply research-only safe fused kernels to the certified gestalt evaluator.

The repository deliberately forbids unsafe code, so this probe does not use std::arch intrinsics.
Instead it fuses the overwhelmingly common sparse NNUE delta shapes into single safe loops and lets
LLVM target the runner CPU. Qualification compiles scalar control and fused candidate with identical
`target-cpu=native` flags, preserving a causal timing comparison and the no-unsafe invariant.
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
        let row = self.feature_row(bucket, feature);
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

    #[inline]
    fn feature_row(&self, bucket: u8, feature: u16) -> &[i16] {
        let start = (usize::from(bucket) * INPUTS + usize::from(feature)) * HIDDEN;
        &self.feature_weights[start..start + HIDDEN]
    }

    fn apply_delta(
        &self,
        values: &mut [i16; HIDDEN],
        bucket: u8,
        delta: FeatureDelta,
        reverse: bool,
    ) {
        let removed = delta.removed();
        let added = delta.added();
        match (removed, added) {
            ([remove], [add]) => fused_delta_1_1(
                values,
                self.feature_row(bucket, *remove),
                self.feature_row(bucket, *add),
                reverse,
            ),
            ([remove_a, remove_b], [add]) => fused_delta_2_1(
                values,
                self.feature_row(bucket, *remove_a),
                self.feature_row(bucket, *remove_b),
                self.feature_row(bucket, *add),
                reverse,
            ),
            ([remove_a, remove_b], [add_a, add_b]) => fused_delta_2_2(
                values,
                self.feature_row(bucket, *remove_a),
                self.feature_row(bucket, *remove_b),
                self.feature_row(bucket, *add_a),
                self.feature_row(bucket, *add_b),
                reverse,
            ),
            _ => {
                if reverse {
                    for &feature in added {
                        self.apply_feature(values, bucket, feature, Direction::Subtract);
                    }
                    for &feature in removed {
                        self.apply_feature(values, bucket, feature, Direction::Add);
                    }
                } else {
                    for &feature in removed {
                        self.apply_feature(values, bucket, feature, Direction::Subtract);
                    }
                    for &feature in added {
                        self.apply_feature(values, bucket, feature, Direction::Add);
                    }
                }
            }
        }
    }
'''
    text = replace_exact(text, old_apply, new_apply, label="feature/delta kernels")

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
    helpers = '''#[inline]
fn fused_delta_1_1(
    values: &mut [i16; HIDDEN],
    removed: &[i16],
    added: &[i16],
    reverse: bool,
) {
    for ((value, &remove), &add) in values.iter_mut().zip(removed).zip(added) {
        *value = if reverse {
            value.wrapping_sub(add).wrapping_add(remove)
        } else {
            value.wrapping_sub(remove).wrapping_add(add)
        };
    }
}

#[inline]
fn fused_delta_2_1(
    values: &mut [i16; HIDDEN],
    removed_a: &[i16],
    removed_b: &[i16],
    added: &[i16],
    reverse: bool,
) {
    for (((value, &remove_a), &remove_b), &add) in values
        .iter_mut()
        .zip(removed_a)
        .zip(removed_b)
        .zip(added)
    {
        *value = if reverse {
            value
                .wrapping_sub(add)
                .wrapping_add(remove_a)
                .wrapping_add(remove_b)
        } else {
            value
                .wrapping_sub(remove_a)
                .wrapping_sub(remove_b)
                .wrapping_add(add)
        };
    }
}

#[inline]
fn fused_delta_2_2(
    values: &mut [i16; HIDDEN],
    removed_a: &[i16],
    removed_b: &[i16],
    added_a: &[i16],
    added_b: &[i16],
    reverse: bool,
) {
    for ((((value, &remove_a), &remove_b), &add_a), &add_b) in values
        .iter_mut()
        .zip(removed_a)
        .zip(removed_b)
        .zip(added_a)
        .zip(added_b)
    {
        *value = if reverse {
            value
                .wrapping_sub(add_a)
                .wrapping_sub(add_b)
                .wrapping_add(remove_a)
                .wrapping_add(remove_b)
        } else {
            value
                .wrapping_sub(remove_a)
                .wrapping_sub(remove_b)
                .wrapping_add(add_a)
                .wrapping_add(add_b)
        };
    }
}

'''
    if text.count(marker) != 1:
        raise PatchError(f"helper insertion marker: expected one occurrence, found {text.count(marker)}")
    text = text.replace(marker, helpers + marker, 1)

    path.write_text(text, encoding="utf-8")
    print("applied safe fused 1+1 / 2+1 / 2+2 gestalt delta kernels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
