//! Research-only scalar compatibility oracle for the CC0 Viridithas v13 `gestalt` network.
//!
//! This intentionally does no incremental updates or SIMD. It exists to prove the byte layout,
//! feature mapping and integer inference against the MIT-licensed Viridithas v13 executable before
//! any search integration is attempted.

use std::{env, fs, path::Path};

use chess_core::{Color, PieceKind, Position, Square};

const INPUTS: usize = 768;
const HIDDEN: usize = 1536;
const BUCKETS: usize = 9;
const QA: i32 = 255;
const QB: i32 = 64;
const SCALE: i32 = 400;
const FEATURE_WEIGHTS: usize = INPUTS * HIDDEN * BUCKETS;
const OUTPUT_WEIGHTS: usize = HIDDEN * 2;
const SERIALIZED_BYTES: usize = 21_242_944;
const PAYLOAD_BYTES: usize = (FEATURE_WEIGHTS + HIDDEN + OUTPUT_WEIGHTS + 1) * 2;

#[rustfmt::skip]
const BUCKET_MAP: [usize; 64] = [
     0,  1,  2,  3, 12, 11, 10,  9,
     4,  4,  5,  5, 14, 14, 13, 13,
     6,  6,  6,  6, 15, 15, 15, 15,
     7,  7,  7,  7, 16, 16, 16, 16,
     8,  8,  8,  8, 17, 17, 17, 17,
     8,  8,  8,  8, 17, 17, 17, 17,
     8,  8,  8,  8, 17, 17, 17, 17,
     8,  8,  8,  8, 17, 17, 17, 17,
];

struct Network {
    feature_weights: Box<[i16]>,
    feature_bias: Box<[i16]>,
    output_weights: Box<[i16]>,
    output_bias: i16,
}

impl Network {
    fn load(path: &Path) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|error| format!("read {}: {error}", path.display()))?;
        if bytes.len() != SERIALIZED_BYTES {
            return Err(format!(
                "gestalt network size mismatch: expected {SERIALIZED_BYTES}, got {}",
                bytes.len()
            ));
        }
        if PAYLOAD_BYTES > bytes.len() {
            return Err("internal payload-size invariant failed".to_owned());
        }

        let mut cursor = 0usize;
        let feature_weights = read_i16s(&bytes, &mut cursor, FEATURE_WEIGHTS)?;
        let feature_bias = read_i16s(&bytes, &mut cursor, HIDDEN)?;
        let output_weights = read_i16s(&bytes, &mut cursor, OUTPUT_WEIGHTS)?;
        let output_bias = read_i16s(&bytes, &mut cursor, 1)?[0];
        debug_assert_eq!(cursor, PAYLOAD_BYTES);

        // The original `NNUEParams` is 64-byte aligned. Its final i16 bias is followed by struct
        // padding to the next 64-byte boundary; those bytes are not part of the learned model.
        if bytes.len() - cursor != 62 {
            return Err(format!(
                "unexpected gestalt trailing alignment: {} bytes",
                bytes.len() - cursor
            ));
        }

        Ok(Self {
            feature_weights,
            feature_bias,
            output_weights,
            output_bias,
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

        let white_bucket = bucket(white_king);
        let black_bucket = bucket(flip_rank(black_king));

        for color in Color::ALL {
            for kind in PieceKind::ALL {
                for square in position.pieces(color, kind) {
                    let white_feature = feature_index(Color::White, white_king, color, kind, square);
                    let black_feature = feature_index(Color::Black, black_king, color, kind, square);
                    self.add_feature(&mut white, white_bucket, white_feature);
                    self.add_feature(&mut black, black_bucket, black_feature);
                }
            }
        }

        let (us, them) = match position.side_to_move() {
            Color::White => (&white, &black),
            Color::Black => (&black, &white),
        };
        let mut output = 0_i64;
        for (index, &value) in us.iter().enumerate() {
            let clipped = i64::from(value.clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[index]);
        }
        for (index, &value) in them.iter().enumerate() {
            let clipped = i64::from(value.clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[HIDDEN + index]);
        }

        // Viridithas divides the SCReLU dot product by QA before adding the QA*QB bias.
        output /= i64::from(QA);
        output += i64::from(self.output_bias);
        output *= i64::from(SCALE);
        output /= i64::from(QA * QB);
        i32::try_from(output).map_err(|_| format!("network output outside i32: {output}"))
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
}

fn read_i16s(bytes: &[u8], cursor: &mut usize, count: usize) -> Result<Box<[i16]>, String> {
    let byte_count = count
        .checked_mul(2)
        .ok_or_else(|| "network field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "network cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated network payload".to_owned())?;
    let values = slice
        .chunks_exact(2)
        .map(|pair| i16::from_le_bytes([pair[0], pair[1]]))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(values)
}

fn king_square(position: &Position, color: Color) -> Result<Square, String> {
    let mut kings = position.pieces(color, PieceKind::King).into_iter();
    let king = kings.next().ok_or_else(|| format!("missing {color:?} king"))?;
    if kings.next().is_some() {
        return Err(format!("multiple {color:?} kings"));
    }
    Ok(king)
}

#[inline]
fn bucket(king: Square) -> usize {
    BUCKET_MAP[usize::from(king.index())] % BUCKETS
}

#[inline]
fn flip_file(square: Square) -> Square {
    Square::from_file_rank(7 - square.file(), square.rank()).expect("flipped file is on board")
}

#[inline]
fn flip_rank(square: Square) -> Square {
    Square::from_file_rank(square.file(), 7 - square.rank()).expect("flipped rank is on board")
}

fn feature_index(
    perspective: Color,
    perspective_king: Square,
    piece_color: Color,
    kind: PieceKind,
    square: Square,
) -> usize {
    let square = if perspective_king.file() >= 4 {
        flip_file(square)
    } else {
        square
    };
    let square = if perspective == Color::Black {
        flip_rank(square)
    } else {
        square
    };
    let relative_color = usize::from(piece_color != perspective);
    relative_color * 6 * 64 + kind.index() * 64 + usize::from(square.index())
}

fn main() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let network = args
        .next()
        .map(Path::new)
        .ok_or_else(|| "usage: viri13_oracle <gestalt-b840.nnue> '<FEN>'".to_owned())?;
    let fen = args
        .next()
        .ok_or_else(|| "usage: viri13_oracle <gestalt-b840.nnue> '<FEN>'".to_owned())?;
    if args.next().is_some() {
        return Err("FEN must be passed as one quoted argument".to_owned());
    }
    let fen = fen
        .into_string()
        .map_err(|_| "FEN is not valid UTF-8".to_owned())?;
    let position = Position::from_fen(&fen).map_err(|error| format!("invalid FEN: {error}"))?;
    let network = Network::load(network)?;
    println!("{}", network.evaluate(&position)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, PieceKind, Square};

    use super::{BUCKETS, PAYLOAD_BYTES, SERIALIZED_BYTES, bucket, feature_index};

    #[test]
    fn serialized_size_matches_v13_aligned_layout() {
        assert_eq!(SERIALIZED_BYTES - PAYLOAD_BYTES, 62);
        assert_eq!(SERIALIZED_BYTES % 64, 0);
    }

    #[test]
    fn bucket_map_is_nine_weights_with_horizontal_mirroring() {
        let a1 = Square::from_file_rank(0, 0).expect("a1");
        let h1 = Square::from_file_rank(7, 0).expect("h1");
        assert_eq!(bucket(a1), bucket(h1));
        for index in 0..64 {
            let square = Square::from_index(index).expect("board square");
            assert!(bucket(square) < BUCKETS);
        }
    }

    #[test]
    fn perspective_inputs_swap_ownership_and_flip_black_rank() {
        let white_king = Square::from_file_rank(3, 0).expect("d1");
        let black_king = Square::from_file_rank(3, 7).expect("d8");
        let a2 = Square::from_file_rank(0, 1).expect("a2");
        assert_eq!(
            feature_index(Color::White, white_king, Color::White, PieceKind::Pawn, a2),
            8
        );
        assert_eq!(
            feature_index(Color::Black, black_king, Color::White, PieceKind::Pawn, a2),
            6 * 64 + 48
        );
    }
}
