#!/usr/bin/env python3
"""Cache exact separable gestalt output sums alongside each perspective accumulator.

This removes the 3072-neuron SCReLU/output scan from leaf evaluation. Sparse feature updates
adjust both cached output-weight halves from each neuron's old/new activation; king-frame refreshes
rebuild the affected accumulator and its two sums. The slow full-refresh evaluator remains an
independent oracle.
"""

from __future__ import annotations

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one occurrence, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    path = Path("crates/chess-eval/src/gestalt.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        '''    pub fn evaluate_full(&self, position: &Position) -> Option<i32> {
        let state = AccumulatorState::from_position(self, position)?;
        Some(state.evaluate(self, position.side_to_move()))
    }
''',
        '''    pub fn evaluate_full(&self, position: &Position) -> Option<i32> {
        let mut white = [0_i16; HIDDEN];
        let mut black = [0_i16; HIDDEN];
        self.rebuild_perspective(position, Color::White, &mut white)?;
        self.rebuild_perspective(position, Color::Black, &mut black)?;
        Some(self.score_accumulators(&white, &black, position.side_to_move()))
    }
''',
        "independent full oracle",
    )

    score_marker = '''    fn score_accumulators(
        &self,
        white: &[i16; HIDDEN],
        black: &[i16; HIDDEN],
        side_to_move: Color,
    ) -> i32 {
'''
    if text.count(score_marker) != 1:
        raise PatchError("score marker missing")

    end_marker = '''        i32::try_from(output).expect("gestalt quantised output remains within i32")
    }
}

/// Perspective coordinate frame.'''
    replacement = '''        i32::try_from(output).expect("gestalt quantised output remains within i32")
    }

    fn output_sums(&self, values: &[i16; HIDDEN]) -> (i64, i64) {
        let mut ours = 0_i64;
        let mut theirs = 0_i64;
        for (index, &value) in values.iter().enumerate() {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            let squared = clipped * clipped;
            ours += squared * i64::from(self.output_weights[index]);
            theirs += squared * i64::from(self.output_weights[HIDDEN + index]);
        }
        (ours, theirs)
    }

    fn finalize_raw_output(&self, mut output: i64) -> i32 {
        output /= i64::from(QA);
        output += i64::from(self.output_bias);
        output *= i64::from(SCALE);
        output /= i64::from(QA * QB);
        i32::try_from(output).expect("gestalt quantised output remains within i32")
    }

    fn apply_feature_cached(
        &self,
        accumulator: &mut PerspectiveAccumulator,
        feature: u16,
        direction: Direction,
    ) {
        let start = (usize::from(accumulator.frame.bucket) * INPUTS + usize::from(feature)) * HIDDEN;
        let row = &self.feature_weights[start..start + HIDDEN];
        for (index, (value, &weight)) in accumulator.values.iter_mut().zip(row).enumerate() {
            let old = *value;
            let new = match direction {
                Direction::Add => old.wrapping_add(weight),
                Direction::Subtract => old.wrapping_sub(weight),
            };
            let old_clipped = i64::from(i32::from(old).clamp(0, QA));
            let new_clipped = i64::from(i32::from(new).clamp(0, QA));
            let delta_squared = new_clipped * new_clipped - old_clipped * old_clipped;
            accumulator.output_ours += delta_squared * i64::from(self.output_weights[index]);
            accumulator.output_theirs +=
                delta_squared * i64::from(self.output_weights[HIDDEN + index]);
            *value = new;
        }
    }
}

/// Perspective coordinate frame.'''
    text = replace_exact(text, end_marker, replacement, "cached network helpers")

    text = replace_exact(
        text,
        '''struct PerspectiveAccumulator {
    frame: Frame,
    values: [i16; HIDDEN],
}
''',
        '''struct PerspectiveAccumulator {
    frame: Frame,
    values: [i16; HIDDEN],
    output_ours: i64,
    output_theirs: i64,
}
''',
        "perspective cached sums",
    )

    old_init = '''        let white_frame = network.rebuild_perspective(position, Color::White, &mut white)?;
        let black_frame = network.rebuild_perspective(position, Color::Black, &mut black)?;
        Some(Self {
            white: PerspectiveAccumulator {
                frame: white_frame,
                values: white,
            },
            black: PerspectiveAccumulator {
                frame: black_frame,
                values: black,
            },
        })
'''
    new_init = '''        let white_frame = network.rebuild_perspective(position, Color::White, &mut white)?;
        let black_frame = network.rebuild_perspective(position, Color::Black, &mut black)?;
        let (white_ours, white_theirs) = network.output_sums(&white);
        let (black_ours, black_theirs) = network.output_sums(&black);
        Some(Self {
            white: PerspectiveAccumulator {
                frame: white_frame,
                values: white,
                output_ours: white_ours,
                output_theirs: white_theirs,
            },
            black: PerspectiveAccumulator {
                frame: black_frame,
                values: black,
                output_ours: black_ours,
                output_theirs: black_theirs,
            },
        })
'''
    text = replace_exact(text, old_init, new_init, "root cached sums")

    text = replace_exact(
        text,
        '''    pub fn evaluate(&self, network: &Network, side_to_move: Color) -> i32 {
        network.score_accumulators(&self.white.values, &self.black.values, side_to_move)
    }
''',
        '''    pub fn evaluate(&self, network: &Network, side_to_move: Color) -> i32 {
        let raw = match side_to_move {
            Color::White => self.white.output_ours + self.black.output_theirs,
            Color::Black => self.black.output_ours + self.white.output_theirs,
        };
        network.finalize_raw_output(raw)
    }
''',
        "O(1) cached evaluation",
    )

    old_refresh = '''            if !reverse {
                debug_assert_eq!(rebuilt, expected_child);
            }
            accumulator.frame = rebuilt;
'''
    new_refresh = '''            if !reverse {
                debug_assert_eq!(rebuilt, expected_child);
            }
            accumulator.frame = rebuilt;
            (accumulator.output_ours, accumulator.output_theirs) =
                network.output_sums(&accumulator.values);
'''
    text = replace_exact(text, old_refresh, new_refresh, "refresh cached sums")

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
            if reverse {
                for &feature in delta.added() {
                    network.apply_feature_cached(accumulator, feature, Direction::Subtract);
                }
                for &feature in delta.removed() {
                    network.apply_feature_cached(accumulator, feature, Direction::Add);
                }
            } else {
                for &feature in delta.removed() {
                    network.apply_feature_cached(accumulator, feature, Direction::Subtract);
                }
                for &feature in delta.added() {
                    network.apply_feature_cached(accumulator, feature, Direction::Add);
                }
            }
        }
'''
    text = replace_exact(text, old_delta, new_delta, "cached sparse updates")

    path.write_text(text, encoding="utf-8")
    print("applied exact cached-output gestalt state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
