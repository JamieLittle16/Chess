//! Research-only scalar compatibility oracle for the Viridithas v16 `perseverance` network.
//!
//! The input is the decompressed quantised network payload. This deliberately avoids incremental
//! state and SIMD so byte layout, feature geometry, output bucketing and deep-head semantics can be
//! certified independently against the MIT-licensed Viridithas v16 executable.

use std::{
    env, fs,
    path::{Path, PathBuf},
};

use chess_core::{Color, PieceKind, Position, Square};

const INPUTS: usize = 11 * 64;
const HIDDEN: usize = 2_048;
const HALF_HIDDEN: usize = HIDDEN / 2;
const BUCKETS: usize = 16;
const L2_SIZE: usize = 16;
const L3_SIZE: usize = 32;
const OUTPUT_BUCKETS: usize = 8;
const QA: i32 = 255;
const QB: i32 = 64;
const SCALE: f32 = 400.0;
const FT_SHIFT: u32 = 10;
const L1_MUL: f32 = (1_u32 << FT_SHIFT) as f32 / (QA * QA * QB) as f32;

const FEATURE_WEIGHTS: usize = INPUTS * HIDDEN * BUCKETS;
const L1_WEIGHTS: usize = HIDDEN * OUTPUT_BUCKETS * L2_SIZE;
const L1_BIASES: usize = OUTPUT_BUCKETS * L2_SIZE;
const L2_WEIGHTS: usize = L2_SIZE * OUTPUT_BUCKETS * L3_SIZE;
const L2_BIASES: usize = OUTPUT_BUCKETS * L3_SIZE;
const L3_WEIGHTS: usize = L3_SIZE * OUTPUT_BUCKETS;
const L3_BIASES: usize = OUTPUT_BUCKETS;
const SERIALIZED_BYTES: usize = FEATURE_WEIGHTS * 2
    + HIDDEN * 2
    + L1_WEIGHTS
    + L1_BIASES * 4
    + L2_WEIGHTS * 4
    + L2_BIASES * 4
    + L3_WEIGHTS * 4
    + L3_BIASES * 4;

#[rustfmt::skip]
const HALF_BUCKET_MAP: [usize; 32] = [
     0,  1,  2,  3,
     4,  5,  6,  7,
     8,  9, 10, 11,
     8,  9, 10, 11,
    12, 12, 13, 13,
    12, 12, 13, 13,
    14, 14, 15, 15,
    14, 14, 15, 15,
];

struct Network {
    feature_weights: Box<[i16]>,
    feature_bias: Box<[i16]>,
    l1_weights: Box<[i8]>,
    l1_bias: Box<[f32]>,
    l2_weights: Box<[f32]>,
    l2_bias: Box<[f32]>,
    l3_weights: Box<[f32]>,
    l3_bias: Box<[f32]>,
}

impl Network {
    fn load(path: &Path) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|error| format!("read {}: {error}", path.display()))?;
        if bytes.len() != SERIALIZED_BYTES {
            return Err(format!(
                "perseverance network size mismatch: expected {SERIALIZED_BYTES}, got {}",
                bytes.len()
            ));
        }

        let mut cursor = 0usize;
        let feature_weights = read_i16s(&bytes, &mut cursor, FEATURE_WEIGHTS)?;
        let feature_bias = read_i16s(&bytes, &mut cursor, HIDDEN)?;
        let l1_weights = read_i8s(&bytes, &mut cursor, L1_WEIGHTS)?;
        let l1_bias = read_f32s(&bytes, &mut cursor, L1_BIASES)?;
        let l2_weights = read_f32s(&bytes, &mut cursor, L2_WEIGHTS)?;
        let l2_bias = read_f32s(&bytes, &mut cursor, L2_BIASES)?;
        let l3_weights = read_f32s(&bytes, &mut cursor, L3_WEIGHTS)?;
        let l3_bias = read_f32s(&bytes, &mut cursor, L3_BIASES)?;
        if cursor != bytes.len() {
            return Err(format!(
                "unexpected perseverance trailing bytes: {}",
                bytes.len() - cursor
            ));
        }

        Ok(Self {
            feature_weights,
            feature_bias,
            l1_weights,
            l1_bias,
            l2_weights,
            l2_bias,
            l3_weights,
            l3_bias,
        })
    }

    fn evaluate(&self, position: &Position) -> Result<i32, String> {
        let white_king = king_square(position, Color::White)?;
        let black_king = king_square(position, Color::Black)?;
        let mut white = vec![0_i32; HIDDEN];
        let mut black = vec![0_i32; HIDDEN];
        for (dst, &bias) in white.iter_mut().zip(self.feature_bias.iter()) {
            *dst = i32::from(bias);
        }
        black.copy_from_slice(&white);

        let white_frame = frame_for_king(Color::White, white_king);
        let black_frame = frame_for_king(Color::Black, black_king);
        for color in Color::ALL {
            for kind in PieceKind::ALL {
                for square in position.pieces(color, kind) {
                    let white_feature = feature_index(white_frame, Color::White, color, kind, square);
                    let black_feature = feature_index(black_frame, Color::Black, color, kind, square);
                    self.add_feature(&mut white, white_frame.bucket, white_feature);
                    self.add_feature(&mut black, black_frame.bucket, black_feature);
                }
            }
        }

        let output_bucket = output_bucket(position);
        Ok(self.score_accumulators(
            &white,
            &black,
            position.side_to_move(),
            output_bucket,
        ))
    }

    fn add_feature(&self, accumulator: &mut [i32], bucket: usize, feature: usize) {
        debug_assert!(bucket < BUCKETS);
        debug_assert!(feature < INPUTS);
        let start = (bucket * INPUTS + feature) * HIDDEN;
        for (dst, &weight) in accumulator
            .iter_mut()
            .zip(&self.feature_weights[start..start + HIDDEN])
        {
            *dst += i32::from(weight);
        }
    }

    fn score_accumulators(
        &self,
        white: &[i32],
        black: &[i32],
        side_to_move: Color,
        output_bucket: usize,
    ) -> i32 {
        let (us, them) = match side_to_move {
            Color::White => (white, black),
            Color::Black => (black, white),
        };

        let mut ft = [0_u8; HIDDEN];
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

        let mut l1 = [0.0_f32; L2_SIZE];
        let l1_bias_start = output_bucket * L2_SIZE;
        for index in 0..L2_SIZE {
            let value = (l1_sums[index] as f32)
                .mul_add(L1_MUL, self.l1_bias[l1_bias_start + index])
                .clamp(0.0, 1.0);
            l1[index] = value * value;
        }

        let mut l2 = [0.0_f32; L3_SIZE];
        let l2_bias_start = output_bucket * L3_SIZE;
        l2.copy_from_slice(&self.l2_bias[l2_bias_start..l2_bias_start + L3_SIZE]);
        for (input_index, &input) in l1.iter().enumerate() {
            let start = (input_index * OUTPUT_BUCKETS + output_bucket) * L3_SIZE;
            let weights = &self.l2_weights[start..start + L3_SIZE];
            for (sum, &weight) in l2.iter_mut().zip(weights) {
                *sum = input.mul_add(weight, *sum);
            }
        }
        for value in &mut l2 {
            let clipped = value.clamp(0.0, 1.0);
            *value = clipped * clipped;
        }

        let mut sums = [0.0_f32; 16];
        for (index, &input) in l2.iter().enumerate() {
            let weight = self.l3_weights[index * OUTPUT_BUCKETS + output_bucket];
            let lane = index % sums.len();
            sums[lane] = input.mul_add(weight, sums[lane]);
        }
        let mut active = sums.len();
        while active > 1 {
            let half = active / 2;
            for index in 0..half {
                sums[index] += sums[index + half];
            }
            active = half;
        }
        let output = sums[0] + self.l3_bias[output_bucket];
        (output * SCALE) as i32
    }
}

fn activate_half(accumulator: &[i32], output: &mut [u8]) {
    debug_assert_eq!(accumulator.len(), HIDDEN);
    debug_assert_eq!(output.len(), HALF_HIDDEN);
    for index in 0..HALF_HIDDEN {
        let left = accumulator[index].clamp(0, QA);
        let right = accumulator[HALF_HIDDEN + index].clamp(0, QA);
        let product = (left * right) >> FT_SHIFT;
        output[index] = u8::try_from(product).expect("SCReLU pair product fits u8");
    }
}

#[derive(Clone, Copy)]
struct Frame {
    bucket: usize,
    mirror_files: bool,
}

fn frame_for_king(perspective: Color, king: Square) -> Frame {
    let relative_rank = match perspective {
        Color::White => king.rank(),
        Color::Black => 7 - king.rank(),
    };
    let mirror_files = king.file() >= 4;
    let half_file = if mirror_files {
        7 - king.file()
    } else {
        king.file()
    };
    let half_index = usize::from(relative_rank) * 4 + usize::from(half_file);
    Frame {
        bucket: HALF_BUCKET_MAP[half_index],
        mirror_files,
    }
}

fn feature_index(
    frame: Frame,
    perspective: Color,
    piece_color: Color,
    kind: PieceKind,
    square: Square,
) -> usize {
    let square = if frame.mirror_files {
        flip_file(square)
    } else {
        square
    };
    let square = match perspective {
        Color::White => square,
        Color::Black => flip_rank(square),
    };
    let relative_color = if kind == PieceKind::King {
        0
    } else {
        usize::from(piece_color != perspective)
    };
    let index = relative_color * 6 * 64 + kind.index() * 64 + usize::from(square.index());
    debug_assert!(index < INPUTS);
    index
}

fn output_bucket(position: &Position) -> usize {
    let men: usize = Color::ALL
        .into_iter()
        .flat_map(|color| PieceKind::ALL.into_iter().map(move |kind| (color, kind)))
        .map(|(color, kind)| {
            usize::try_from(position.pieces(color, kind).count()).expect("piece count fits usize")
        })
        .sum();
    men.saturating_sub(2).div_ceil(4).saturating_sub(1).min(OUTPUT_BUCKETS - 1)
}

fn king_square(position: &Position, color: Color) -> Result<Square, String> {
    let mut kings = position.pieces(color, PieceKind::King).into_iter();
    let king = kings
        .next()
        .ok_or_else(|| format!("missing {color:?} king"))?;
    if kings.next().is_some() {
        return Err(format!("multiple {color:?} kings"));
    }
    Ok(king)
}

fn flip_file(square: Square) -> Square {
    Square::from_file_rank(7 - square.file(), square.rank()).expect("file flip stays on board")
}

fn flip_rank(square: Square) -> Square {
    Square::from_file_rank(square.file(), 7 - square.rank()).expect("rank flip stays on board")
}

fn read_i16s(bytes: &[u8], cursor: &mut usize, count: usize) -> Result<Box<[i16]>, String> {
    let byte_count = count
        .checked_mul(2)
        .ok_or_else(|| "i16 field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "network cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated i16 network field".to_owned())?;
    let (pairs, remainder) = slice.as_chunks::<2>();
    if !remainder.is_empty() {
        return Err("odd i16 network field".to_owned());
    }
    let values = pairs
        .iter()
        .map(|pair| i16::from_le_bytes(*pair))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(values)
}

fn read_i8s(bytes: &[u8], cursor: &mut usize, count: usize) -> Result<Box<[i8]>, String> {
    let end = cursor
        .checked_add(count)
        .ok_or_else(|| "network cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated i8 network field".to_owned())?;
    let values = slice
        .iter()
        .map(|&byte| i8::from_le_bytes([byte]))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(values)
}

fn read_f32s(bytes: &[u8], cursor: &mut usize, count: usize) -> Result<Box<[f32]>, String> {
    let byte_count = count
        .checked_mul(4)
        .ok_or_else(|| "f32 field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "network cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated f32 network field".to_owned())?;
    let (quads, remainder) = slice.as_chunks::<4>();
    if !remainder.is_empty() {
        return Err("misaligned f32 network field".to_owned());
    }
    let values = quads
        .iter()
        .map(|quad| f32::from_le_bytes(*quad))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(values)
}

fn main() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let network = args
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "usage: viri16_oracle <perseverance.bin> '<FEN>'".to_owned())?;
    let fen = args
        .next()
        .ok_or_else(|| "usage: viri16_oracle <perseverance.bin> '<FEN>'".to_owned())?;
    if args.next().is_some() {
        return Err("FEN must be passed as one quoted argument".to_owned());
    }
    let fen = fen
        .into_string()
        .map_err(|_| "FEN is not valid UTF-8".to_owned())?;
    let position = Position::from_fen(&fen).map_err(|error| format!("invalid FEN: {error}"))?;
    let network = Network::load(&network)?;
    println!("{}", network.evaluate(&position)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, PieceKind, Position, Square};

    use super::{BUCKETS, INPUTS, SERIALIZED_BYTES, feature_index, frame_for_king, output_bucket};

    #[test]
    fn serialized_size_matches_v16_quantised_layout() {
        assert_eq!(SERIALIZED_BYTES, 46_422_560);
    }

    #[test]
    fn sixteen_bucket_geometry_mirrors_files() {
        let a1 = Square::from_file_rank(0, 0).expect("a1");
        let h1 = Square::from_file_rank(7, 0).expect("h1");
        let left = frame_for_king(Color::White, a1);
        let right = frame_for_king(Color::White, h1);
        assert_eq!(left.bucket, right.bucket);
        assert_ne!(left.mirror_files, right.mirror_files);
        assert!(left.bucket < BUCKETS);
    }

    #[test]
    fn merged_king_plane_reduces_inputs_to_704() {
        let king = Square::from_file_rank(3, 0).expect("d1");
        let frame = frame_for_king(Color::White, king);
        let enemy_king = Square::from_file_rank(3, 7).expect("d8");
        let index = feature_index(frame, Color::White, Color::Black, PieceKind::King, enemy_king);
        assert!(index < INPUTS);
        assert_eq!(index / 64, PieceKind::King.index());
    }

    #[test]
    fn material_output_buckets_span_eight_heads() {
        assert_eq!(output_bucket(&Position::startpos()), 7);
        let kings = Position::from_fen("7k/8/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        assert_eq!(output_bucket(&kings), 0);
    }
}
