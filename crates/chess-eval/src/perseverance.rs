//! Reversible runtime for the Viridithas v16 `perseverance` evaluator generation.
//!
//! The file format is the decompressed quantised payload from the CC0 network release. The feature
//! transformer keeps the same derived-state contract as `gestalt`: ordinary legal moves update only
//! their sparse rows, while a king-frame change rebuilds the affected perspective. The deeper head
//! remains a pure read of the already-materialised accumulators.

use std::{fs, path::Path};

use chess_core::{ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square};

pub const INPUTS: usize = 11 * 64;
pub const HIDDEN: usize = 2_048;
pub const BUCKETS: usize = 16;
pub const SERIALIZED_BYTES: usize = 46_422_560;

const HALF_HIDDEN: usize = HIDDEN / 2;
const L2_SIZE: usize = 16;
const L3_SIZE: usize = 32;
const OUTPUT_BUCKETS: usize = 8;
const QA: i32 = 255;
const QB: i32 = 64;
const SCALE: f32 = 400.0;
const FT_SHIFT: u32 = 10;
const L1_MUL: f32 = (1_u32 << FT_SHIFT) as f32 / (QA * QA * QB) as f32;
const MAX_DELTA_FEATURES: usize = 4;

const FEATURE_WEIGHTS: usize = INPUTS * HIDDEN * BUCKETS;
const L1_WEIGHTS: usize = HIDDEN * OUTPUT_BUCKETS * L2_SIZE;
const L1_BIASES: usize = OUTPUT_BUCKETS * L2_SIZE;
const L2_WEIGHTS: usize = L2_SIZE * OUTPUT_BUCKETS * L3_SIZE;
const L2_BIASES: usize = OUTPUT_BUCKETS * L3_SIZE;
const L3_WEIGHTS: usize = L3_SIZE * OUTPUT_BUCKETS;
const L3_BIASES: usize = OUTPUT_BUCKETS;

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

/// Exact decompressed v16 quantised parameters in their release-file ordering.
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
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() != SERIALIZED_BYTES {
            return Err(format!(
                "perseverance network size mismatch: expected {SERIALIZED_BYTES}, got {}",
                bytes.len()
            ));
        }

        let mut cursor = 0usize;
        let feature_weights = read_i16s(bytes, &mut cursor, FEATURE_WEIGHTS)?;
        let feature_bias = read_i16s(bytes, &mut cursor, HIDDEN)?;
        let l1_weights = read_i8s(bytes, &mut cursor, L1_WEIGHTS)?;
        let l1_bias = read_f32s(bytes, &mut cursor, L1_BIASES)?;
        let l2_weights = read_f32s(bytes, &mut cursor, L2_WEIGHTS)?;
        let l2_bias = read_f32s(bytes, &mut cursor, L2_BIASES)?;
        let l3_weights = read_f32s(bytes, &mut cursor, L3_WEIGHTS)?;
        let l3_bias = read_f32s(bytes, &mut cursor, L3_BIASES)?;
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

    pub fn from_file(path: &Path) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|error| format!("read {}: {error}", path.display()))?;
        Self::from_bytes(&bytes)
    }

    #[must_use]
    pub fn evaluate_full(&self, position: &Position) -> Option<i32> {
        let state = AccumulatorState::from_position(self, position)?;
        Some(state.evaluate(self, position))
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
                    self.apply_feature(values, frame.bucket, feature, Direction::Add);
                }
            }
        }
        Some(frame)
    }

    fn feature_row(&self, bucket: u8, feature: u16) -> &[i16] {
        let start = (usize::from(bucket) * INPUTS + usize::from(feature)) * HIDDEN;
        &self.feature_weights[start..start + HIDDEN]
    }

    fn apply_feature(
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

    #[allow(clippy::cast_possible_truncation, clippy::cast_precision_loss)]
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
        let output_bucket = output_bucket(position);

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

        let l1_bias_start = output_bucket * L2_SIZE;
        let mut l1 = [0.0_f32; L2_SIZE];
        for index in 0..L2_SIZE {
            let value = (l1_sums[index] as f32)
                .mul_add(L1_MUL, self.l1_bias[l1_bias_start + index])
                .clamp(0.0, 1.0);
            l1[index] = value * value;
        }

        let l2_bias_start = output_bucket * L3_SIZE;
        let mut l2 = [0.0_f32; L3_SIZE];
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
        ((sums[0] + self.l3_bias[output_bucket]) * SCALE) as i32
    }
}

fn activate_half(accumulator: &[i16; HIDDEN], output: &mut [u8]) {
    debug_assert_eq!(output.len(), HALF_HIDDEN);
    for index in 0..HALF_HIDDEN {
        let left = i32::from(accumulator[index]).clamp(0, QA);
        let right = i32::from(accumulator[HALF_HIDDEN + index]).clamp(0, QA);
        let product = (left * right) >> FT_SHIFT;
        output[index] = u8::try_from(product).expect("SCReLU pair product fits u8");
    }
}

#[inline]
fn fused_delta_1_1(values: &mut [i16; HIDDEN], removed: &[i16], added: &[i16], reverse: bool) {
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
    for (((value, &remove_a), &remove_b), &add) in
        values.iter_mut().zip(removed_a).zip(removed_b).zip(added)
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
    Refresh(Frame),
    Delta(FeatureDelta),
}

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
            return Some(PerspectiveUpdate::Refresh(next));
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
        PerspectiveUpdate::Refresh(expected_child) => {
            let rebuilt = network.rebuild_perspective(position, perspective, &mut accumulator.values)?;
            if !reverse {
                debug_assert_eq!(rebuilt, expected_child);
            }
            accumulator.frame = rebuilt;
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

#[derive(Clone, Copy)]
enum Direction {
    Add,
    Subtract,
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
    let relative_color = if piece.kind() == PieceKind::King {
        0
    } else {
        usize::from(piece.color() != perspective)
    };
    let raw = relative_color * 6 * 64 + piece.kind().index() * 64 + usize::from(square.index());
    debug_assert!(raw < INPUTS);
    u16::try_from(raw).expect("perseverance feature index fits u16")
}

fn output_bucket(position: &Position) -> usize {
    let men: usize = Color::ALL
        .into_iter()
        .flat_map(|color| PieceKind::ALL.into_iter().map(move |kind| (color, kind)))
        .map(|(color, kind)| {
            usize::try_from(position.pieces(color, kind).count()).expect("piece count fits usize")
        })
        .sum();
    (men.saturating_sub(2) / 4).min(OUTPUT_BUCKETS - 1)
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
        .ok_or_else(|| "perseverance i16 field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "perseverance cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated perseverance i16 field".to_owned())?;
    let (pairs, remainder) = slice.as_chunks::<2>();
    if !remainder.is_empty() {
        return Err("odd perseverance i16 field length".to_owned());
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
        .ok_or_else(|| "perseverance cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated perseverance i8 field".to_owned())?;
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
        .ok_or_else(|| "perseverance f32 field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "perseverance cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated perseverance f32 field".to_owned())?;
    let (quads, remainder) = slice.as_chunks::<4>();
    if !remainder.is_empty() {
        return Err("misaligned perseverance f32 field".to_owned());
    }
    let values = quads
        .iter()
        .map(|quad| f32::from_le_bytes(*quad))
        .collect::<Vec<_>>()
        .into_boxed_slice();
    *cursor = end;
    Ok(values)
}

#[cfg(test)]
mod tests {
    use std::mem::size_of;

    use super::*;

    #[test]
    fn serialized_layout_matches_v16_payload() {
        assert_eq!(SERIALIZED_BYTES, 46_422_560);
    }

    #[test]
    fn prepared_update_remains_small_stack_state() {
        assert!(size_of::<PreparedAccumulatorUpdate>() <= 64);
    }

    #[test]
    fn output_bucket_matches_v16_material_partition() {
        assert_eq!(output_bucket(&Position::startpos()), 7);
        let kings = Position::from_fen("7k/8/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        assert_eq!(output_bucket(&kings), 0);
        let six_men =
            Position::from_fen("7k/8/8/8/8/8/PP2pp2/K7 w - - 0 1").expect("valid FEN");
        assert_eq!(output_bucket(&six_men), 1);
    }

    #[test]
    fn incremental_push_pop_matches_full_refresh() {
        let network = patterned_network();
        let root = Position::startpos();
        let mut position = root.clone();
        let mut state = AccumulatorState::from_position(&network, &position).expect("legal root");
        assert_state_matches(&network, &state, &position);
        let original_state = state.clone();

        let mut history = Vec::new();
        for ply in 0..64_usize {
            let moves = position.legal_moves();
            if moves.is_empty() {
                break;
            }
            let mv = moves[(ply.wrapping_mul(29).wrapping_add(11)) % moves.len()];
            let prepared = AccumulatorState::prepare_move(&position, mv).expect("prepare move");
            let undo = position.make_move(mv);
            state
                .apply_prepared(&network, &position, prepared)
                .expect("apply child");
            assert_state_matches(&network, &state, &position);
            history.push((mv, undo, prepared));
        }

        while let Some((mv, undo, prepared)) = history.pop() {
            position.unmake_move(mv, undo);
            state
                .restore_after_unmake(&network, &position, prepared)
                .expect("restore parent");
            assert_state_matches(&network, &state, &position);
        }
        assert_eq!(position, root);
        assert_eq!(state, original_state);
    }

    #[test]
    fn special_moves_and_bucket_refresh_round_trip() {
        let network = patterned_network();
        for (fen, from, to, kind) in [
            (
                "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
                square(4, 0),
                square(6, 0),
                None,
            ),
            (
                "k7/8/8/4KPp1/8/8/8/8 w - g6 0 1",
                square(5, 4),
                square(6, 5),
                None,
            ),
            (
                "7k/P7/8/8/8/8/8/K7 w - - 0 1",
                square(0, 6),
                square(0, 7),
                Some(MoveKind::PromoteQueen),
            ),
            (
                "7k/8/8/8/8/8/8/4K3 w - - 0 1",
                square(4, 0),
                square(5, 0),
                None,
            ),
        ] {
            assert_round_trip(&network, fen, from, to, kind);
        }
    }

    fn assert_round_trip(
        network: &Network,
        fen: &str,
        from: Square,
        to: Square,
        kind: Option<MoveKind>,
    ) {
        let mut position = Position::from_fen(fen).expect("valid special FEN");
        let root = position.clone();
        let mv = position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| {
                mv.from() == from
                    && mv.to() == to
                    && kind.is_none_or(|required| mv.kind() == required)
            })
            .expect("special move exists");
        let mut state = AccumulatorState::from_position(network, &position).expect("root state");
        let root_state = state.clone();
        let prepared = AccumulatorState::prepare_move(&position, mv).expect("prepare");
        let undo = position.make_move(mv);
        state
            .apply_prepared(network, &position, prepared)
            .expect("apply");
        assert_state_matches(network, &state, &position);
        position.unmake_move(mv, undo);
        state
            .restore_after_unmake(network, &position, prepared)
            .expect("restore");
        assert_eq!(position, root);
        assert_eq!(state, root_state);
    }

    fn assert_state_matches(network: &Network, state: &AccumulatorState, position: &Position) {
        let rebuilt = AccumulatorState::from_position(network, position).expect("full rebuild");
        assert_eq!(*state, rebuilt);
    }

    fn patterned_network() -> Network {
        let mut feature_weights = vec![0_i16; FEATURE_WEIGHTS].into_boxed_slice();
        for bucket in 0..BUCKETS {
            for feature in 0..INPUTS {
                let start = (bucket * INPUTS + feature) * HIDDEN;
                for lane in 0..8_usize {
                    feature_weights[start + lane] =
                        i16::try_from((bucket + feature + lane) % 7).expect("small value") - 3;
                }
            }
        }
        let mut feature_bias = vec![0_i16; HIDDEN].into_boxed_slice();
        for (index, bias) in feature_bias.iter_mut().enumerate() {
            *bias = 96 + i16::try_from(index % 11).expect("small value") - 5;
        }
        Network {
            feature_weights,
            feature_bias,
            l1_weights: vec![0_i8; L1_WEIGHTS].into_boxed_slice(),
            l1_bias: vec![0.0_f32; L1_BIASES].into_boxed_slice(),
            l2_weights: vec![0.0_f32; L2_WEIGHTS].into_boxed_slice(),
            l2_bias: vec![0.0_f32; L2_BIASES].into_boxed_slice(),
            l3_weights: vec![0.0_f32; L3_WEIGHTS].into_boxed_slice(),
            l3_bias: vec![0.0_f32; L3_BIASES].into_boxed_slice(),
        }
    }
}
