//! Research runtime for the Viridithas v14/v15 `hyperstition` NNUE family.
//!
//! This module intentionally starts with a transparent scalar inference oracle. The feature
//! transformer is still updated incrementally during search; only the small dense tail is scalar.
//! Once parity is certified against the reference implementation, the tail can be SIMD-specialised
//! without changing the network format or accumulator semantics.

#![allow(clippy::cast_possible_truncation, clippy::cast_precision_loss)]

use std::{fs, path::Path};

use chess_core::{ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square};

pub const INPUTS: usize = 768;
pub const HIDDEN: usize = 2_048;
pub const FEATURE_BUCKETS: usize = 16;
pub const OUTPUT_BUCKETS: usize = 8;
pub const L2: usize = 16;
pub const L3: usize = 32;
/// Raw quantised `NNUEParams` size in Viridithas v14, including the 32-byte tail padding imposed by
/// the structure's 64-byte alignment.
pub const SERIALIZED_BYTES: usize = 50_616_896;

const QA: i32 = 255;
const QB: i32 = 64;
const SCALE: f32 = 400.0;
const FEATURE_WEIGHTS: usize = INPUTS * HIDDEN * FEATURE_BUCKETS;
const FEATURE_BIAS: usize = HIDDEN;
const L1_WEIGHTS: usize = OUTPUT_BUCKETS * HIDDEN * L2;
const L1_BIAS: usize = OUTPUT_BUCKETS * L2;
const L2_WEIGHTS: usize = OUTPUT_BUCKETS * L2 * L3;
const L2_BIAS: usize = OUTPUT_BUCKETS * L3;
const L3_WEIGHTS: usize = OUTPUT_BUCKETS * L3;
const L3_BIAS: usize = OUTPUT_BUCKETS;
const PAYLOAD_BYTES: usize = SERIALIZED_BYTES - 32;
const MAX_DELTA_FEATURES: usize = 4;

#[rustfmt::skip]
const HALF_BUCKET_MAP: [u8; 32] = [
     0,  1,  2,  3,
     4,  5,  6,  7,
     8,  9, 10, 11,
     8,  9, 10, 11,
    12, 12, 13, 13,
    12, 12, 13, 13,
    14, 14, 15, 15,
    14, 14, 15, 15,
];

/// Exact quantised parameters for the v14/v15 Hyperstition architecture.
pub struct Network {
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
    /// Parse the decompressed Viridithas v14 quantised struct representation.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() != SERIALIZED_BYTES {
            return Err(format!(
                "hyperstition network size mismatch: expected {SERIALIZED_BYTES}, got {}",
                bytes.len()
            ));
        }
        let mut cursor = 0_usize;
        let feature_weights = read_i16s(bytes, &mut cursor, FEATURE_WEIGHTS)?;
        let feature_bias = read_i16s(bytes, &mut cursor, FEATURE_BIAS)?;
        let l1_weights = read_i8s(bytes, &mut cursor, L1_WEIGHTS)?;
        let l1_bias = read_f32s(bytes, &mut cursor, L1_BIAS)?;
        let l2_weights = read_f32s(bytes, &mut cursor, L2_WEIGHTS)?;
        let l2_bias = read_f32s(bytes, &mut cursor, L2_BIAS)?;
        let l3_weights = read_f32s(bytes, &mut cursor, L3_WEIGHTS)?;
        let l3_bias = read_f32s(bytes, &mut cursor, L3_BIAS)?;
        if cursor != PAYLOAD_BYTES {
            return Err(format!(
                "unexpected hyperstition payload boundary: {cursor} != {PAYLOAD_BYTES}"
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

    /// Load an already-decompressed quantised network at engine setup time.
    pub fn from_file(path: &Path) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|error| format!("read {}: {error}", path.display()))?;
        Self::from_bytes(&bytes)
    }

    /// Slow full-refresh evaluation oracle.
    #[must_use]
    pub fn evaluate_full(&self, position: &Position) -> Option<i32> {
        let state = AccumulatorState::from_position(self, position)?;
        Some(state.evaluate(self, position))
    }

    fn feature_row(&self, bucket: u8, feature: u16) -> &[i16] {
        let start = (usize::from(bucket) * INPUTS + usize::from(feature)) * HIDDEN;
        &self.feature_weights[start..start + HIDDEN]
    }

    fn rebuild_perspective(
        &self,
        position: &Position,
        perspective: Color,
        values: &mut [i16; HIDDEN],
    ) -> Option<Frame> {
        let king = position.king_square(perspective)?;
        let frame = frame_for_king(perspective, king);
        values.copy_from_slice(&self.feature_bias);
        for color in Color::ALL {
            for kind in PieceKind::ALL {
                let piece = Piece::new(color, kind);
                for square in position.pieces(color, kind) {
                    let feature = feature_index(frame, perspective, piece, square);
                    for (value, &weight) in values
                        .iter_mut()
                        .zip(self.feature_row(frame.bucket, feature))
                    {
                        *value = value.wrapping_add(weight);
                    }
                }
            }
        }
        Some(frame)
    }

    fn apply_delta(
        &self,
        values: &mut [i16; HIDDEN],
        bucket: u8,
        delta: FeatureDelta,
        reverse: bool,
    ) {
        if reverse {
            for &feature in delta.added() {
                for (value, &weight) in values.iter_mut().zip(self.feature_row(bucket, feature)) {
                    *value = value.wrapping_sub(weight);
                }
            }
            for &feature in delta.removed() {
                for (value, &weight) in values.iter_mut().zip(self.feature_row(bucket, feature)) {
                    *value = value.wrapping_add(weight);
                }
            }
        } else {
            for &feature in delta.removed() {
                for (value, &weight) in values.iter_mut().zip(self.feature_row(bucket, feature)) {
                    *value = value.wrapping_sub(weight);
                }
            }
            for &feature in delta.added() {
                for (value, &weight) in values.iter_mut().zip(self.feature_row(bucket, feature)) {
                    *value = value.wrapping_add(weight);
                }
            }
        }
    }

    fn score_accumulators(
        &self,
        white: &[i16; HIDDEN],
        black: &[i16; HIDDEN],
        position: &Position,
    ) -> i32 {
        let (us, them) = match position.side_to_move() {
            Color::White => (white, black),
            Color::Black => (black, white),
        };
        let bucket = output_bucket(position);
        let mut ft = [0_u8; HIDDEN];
        activate_pairwise(us, &mut ft[..HIDDEN / 2]);
        activate_pairwise(them, &mut ft[HIDDEN / 2..]);

        let l1_weight_base = bucket * HIDDEN * L2;
        let l1_bias_base = bucket * L2;
        let mut l1 = [0_f32; L2];
        for (output, output_value) in l1.iter_mut().enumerate() {
            let row = &self.l1_weights
                [l1_weight_base + output * HIDDEN..l1_weight_base + (output + 1) * HIDDEN];
            let mut sum = 0_i32;
            for (&input, &weight) in ft.iter().zip(row) {
                sum += i32::from(input) * i32::from(weight);
            }
            let value = sum as f32 / (QA * QB) as f32 + self.l1_bias[l1_bias_base + output];
            let clipped = value.clamp(0.0, 1.0);
            *output_value = clipped * clipped;
        }

        let l2_weight_base = bucket * L2 * L3;
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

        let l3_weight_base = bucket * L3;
        let mut output = self.l3_bias[bucket];
        for (&input, &weight) in l2
            .iter()
            .zip(&self.l3_weights[l3_weight_base..l3_weight_base + L3])
        {
            output = input.mul_add(weight, output);
        }
        (output * SCALE) as i32
    }
}

fn activate_pairwise(accumulator: &[i16; HIDDEN], output: &mut [u8]) {
    debug_assert_eq!(output.len(), HIDDEN / 2);
    for index in 0..HIDDEN / 2 {
        let left = i32::from(accumulator[index]).clamp(0, QA);
        let right = i32::from(accumulator[HIDDEN / 2 + index]).clamp(0, QA);
        output[index] = ((left * right) / QA) as u8;
    }
}

fn output_bucket(position: &Position) -> usize {
    let men = Color::ALL
        .into_iter()
        .flat_map(|color| PieceKind::ALL.into_iter().map(move |kind| (color, kind)))
        .map(|(color, kind)| position.pieces(color, kind).count() as usize)
        .sum::<usize>();
    men.saturating_sub(2).div_euclid(4).min(OUTPUT_BUCKETS - 1)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Frame {
    bucket: u8,
    mirror_files: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct FeatureDelta {
    removed: [u16; MAX_DELTA_FEATURES],
    removed_len: u8,
    added: [u16; MAX_DELTA_FEATURES],
    added_len: u8,
}

impl FeatureDelta {
    const fn new() -> Self {
        Self {
            removed: [0; MAX_DELTA_FEATURES],
            removed_len: 0,
            added: [0; MAX_DELTA_FEATURES],
            added_len: 0,
        }
    }

    fn remove(&mut self, feature: u16) {
        let index = usize::from(self.removed_len);
        debug_assert!(index < MAX_DELTA_FEATURES);
        self.removed[index] = feature;
        self.removed_len += 1;
    }

    fn add(&mut self, feature: u16) {
        let index = usize::from(self.added_len);
        debug_assert!(index < MAX_DELTA_FEATURES);
        self.added[index] = feature;
        self.added_len += 1;
    }

    fn removed(&self) -> &[u16] {
        &self.removed[..usize::from(self.removed_len)]
    }

    fn added(&self) -> &[u16] {
        &self.added[..usize::from(self.added_len)]
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum PerspectiveUpdate {
    Refresh,
    Delta(FeatureDelta),
}

/// Small move-derived update retained across recursive search.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PreparedAccumulatorUpdate {
    white: PerspectiveUpdate,
    black: PerspectiveUpdate,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PerspectiveAccumulator {
    frame: Frame,
    values: [i16; HIDDEN],
}

/// Reversible two-perspective feature-transformer state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AccumulatorState {
    white: PerspectiveAccumulator,
    black: PerspectiveAccumulator,
}

impl AccumulatorState {
    #[must_use]
    pub fn from_position(network: &Network, position: &Position) -> Option<Self> {
        let mut white = [0_i16; HIDDEN];
        let mut black = [0_i16; HIDDEN];
        let white_frame = network.rebuild_perspective(position, Color::White, &mut white)?;
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
    }

    #[must_use]
    pub fn prepare_move(position: &Position, mv: ChessMove) -> Option<PreparedAccumulatorUpdate> {
        Some(PreparedAccumulatorUpdate {
            white: prepare_perspective(position, mv, Color::White)?,
            black: prepare_perspective(position, mv, Color::Black)?,
        })
    }

    pub fn apply_prepared(
        &mut self,
        network: &Network,
        position_after: &Position,
        prepared: PreparedAccumulatorUpdate,
    ) -> Option<()> {
        apply_one(
            &mut self.white,
            network,
            position_after,
            Color::White,
            prepared.white,
            false,
        )?;
        apply_one(
            &mut self.black,
            network,
            position_after,
            Color::Black,
            prepared.black,
            false,
        )?;
        Some(())
    }

    pub fn restore_after_unmake(
        &mut self,
        network: &Network,
        restored_position: &Position,
        prepared: PreparedAccumulatorUpdate,
    ) -> Option<()> {
        apply_one(
            &mut self.white,
            network,
            restored_position,
            Color::White,
            prepared.white,
            true,
        )?;
        apply_one(
            &mut self.black,
            network,
            restored_position,
            Color::Black,
            prepared.black,
            true,
        )?;
        Some(())
    }

    #[must_use]
    pub fn evaluate(&self, network: &Network, position: &Position) -> i32 {
        network.score_accumulators(&self.white.values, &self.black.values, position)
    }
}

fn prepare_perspective(
    position: &Position,
    mv: ChessMove,
    perspective: Color,
) -> Option<PerspectiveUpdate> {
    let king = position.king_square(perspective)?;
    let frame = frame_for_king(perspective, king);
    let moving = position.piece_at(mv.from())?;
    if moving.color() == perspective && moving.kind() == PieceKind::King {
        let next = frame_for_king(perspective, mv.to());
        if next != frame {
            return Some(PerspectiveUpdate::Refresh);
        }
    }

    let mut delta = FeatureDelta::new();
    delta.remove(feature_index(frame, perspective, moving, mv.from()));
    if let Some(captured_square) = captured_square(position, moving.color(), mv)
        && let Some(captured) = position.piece_at(captured_square)
    {
        delta.remove(feature_index(frame, perspective, captured, captured_square));
    }
    let resulting = mv
        .kind()
        .promotion_piece()
        .map_or(moving, |kind| Piece::new(moving.color(), kind));
    delta.add(feature_index(frame, perspective, resulting, mv.to()));
    if let Some((rook_from, rook_to)) = castle_rook_displacement(moving.color(), mv.kind()) {
        let rook = Piece::new(moving.color(), PieceKind::Rook);
        delta.remove(feature_index(frame, perspective, rook, rook_from));
        delta.add(feature_index(frame, perspective, rook, rook_to));
    }
    Some(PerspectiveUpdate::Delta(delta))
}

fn apply_one(
    accumulator: &mut PerspectiveAccumulator,
    network: &Network,
    position: &Position,
    perspective: Color,
    update: PerspectiveUpdate,
    reverse: bool,
) -> Option<()> {
    match update {
        PerspectiveUpdate::Refresh => {
            accumulator.frame =
                network.rebuild_perspective(position, perspective, &mut accumulator.values)?;
        }
        PerspectiveUpdate::Delta(delta) => {
            network.apply_delta(
                &mut accumulator.values,
                accumulator.frame.bucket,
                delta,
                reverse,
            );
        }
    }
    Some(())
}

fn frame_for_king(perspective: Color, king: Square) -> Frame {
    let relative = match perspective {
        Color::White => king,
        Color::Black => flip_rank(king),
    };
    let rank = usize::from(relative.rank());
    let file = usize::from(relative.file());
    let half_file = file.min(7 - file);
    let bucket = HALF_BUCKET_MAP[rank * 4 + half_file];
    Frame {
        bucket,
        mirror_files: file >= 4,
    }
}

fn feature_index(frame: Frame, perspective: Color, piece: Piece, square: Square) -> u16 {
    let square = if frame.mirror_files {
        flip_file(square)
    } else {
        square
    };
    let square = match perspective {
        Color::White => square,
        Color::Black => flip_rank(square),
    };
    let ownership = usize::from(piece.color() != perspective);
    let raw = ownership * 6 * 64 + piece.kind().index() * 64 + usize::from(square.index());
    debug_assert!(raw < INPUTS);
    raw as u16
}

fn captured_square(position: &Position, us: Color, mv: ChessMove) -> Option<Square> {
    if mv.kind() == MoveKind::EnPassant {
        let rank = match us {
            Color::White => mv.to().rank().checked_sub(1)?,
            Color::Black => mv.to().rank().checked_add(1)?,
        };
        Square::from_file_rank(mv.to().file(), rank)
    } else if mv.kind().is_capture() && position.piece_at(mv.to()).is_some() {
        Some(mv.to())
    } else {
        None
    }
}

fn castle_rook_displacement(color: Color, kind: MoveKind) -> Option<(Square, Square)> {
    let rank = match color {
        Color::White => 0,
        Color::Black => 7,
    };
    match kind {
        MoveKind::KingCastle => Some((square(7, rank), square(5, rank))),
        MoveKind::QueenCastle => Some((square(0, rank), square(3, rank))),
        _ => None,
    }
}

fn flip_file(square: Square) -> Square {
    Square::from_file_rank(7 - square.file(), square.rank()).expect("file flip stays on board")
}

fn flip_rank(square: Square) -> Square {
    Square::from_file_rank(square.file(), 7 - square.rank()).expect("rank flip stays on board")
}

fn square(file: u8, rank: u8) -> Square {
    Square::from_file_rank(file, rank).expect("constant square stays on board")
}

fn read_i16s(bytes: &[u8], cursor: &mut usize, count: usize) -> Result<Box<[i16]>, String> {
    let byte_count = count
        .checked_mul(2)
        .ok_or_else(|| "i16 field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated i16 payload".to_owned())?;
    let (pairs, remainder) = slice.as_chunks::<2>();
    if !remainder.is_empty() {
        return Err("odd i16 field length".to_owned());
    }
    let result = pairs
        .iter()
        .map(|pair| i16::from_le_bytes(*pair))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(result)
}

fn read_i8s(bytes: &[u8], cursor: &mut usize, count: usize) -> Result<Box<[i8]>, String> {
    let end = cursor
        .checked_add(count)
        .ok_or_else(|| "cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated i8 payload".to_owned())?;
    let result = slice
        .iter()
        .map(|&byte| i8::from_le_bytes([byte]))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(result)
}

fn read_f32s(bytes: &[u8], cursor: &mut usize, count: usize) -> Result<Box<[f32]>, String> {
    let byte_count = count
        .checked_mul(4)
        .ok_or_else(|| "f32 field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated f32 payload".to_owned())?;
    let (words, remainder) = slice.as_chunks::<4>();
    if !remainder.is_empty() {
        return Err("unaligned f32 field length".to_owned());
    }
    let result = words
        .iter()
        .map(|word| f32::from_le_bytes(*word))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn output_bucket_matches_eight_four_man_bands() {
        let start = Position::startpos();
        assert_eq!(output_bucket(&start), 7);
        let kings = Position::from_fen("7k/8/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        assert_eq!(output_bucket(&kings), 0);
    }

    #[test]
    fn king_bucket_and_horizontal_mirror_match_reference_map() {
        let a1 = square(0, 0);
        let h1 = square(7, 0);
        let e1 = square(4, 0);
        assert_eq!(frame_for_king(Color::White, a1).bucket, 0);
        assert!(!frame_for_king(Color::White, a1).mirror_files);
        assert_eq!(frame_for_king(Color::White, h1).bucket, 0);
        assert!(frame_for_king(Color::White, h1).mirror_files);
        assert_eq!(frame_for_king(Color::White, e1).bucket, 3);
        assert!(frame_for_king(Color::White, e1).mirror_files);
    }

    #[test]
    fn prepared_update_remains_small() {
        assert!(std::mem::size_of::<PreparedAccumulatorUpdate>() <= 64);
    }
}
