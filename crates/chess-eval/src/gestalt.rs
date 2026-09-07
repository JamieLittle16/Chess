//! Bit-exact, research-only runtime for the CC0 Viridithas v13 `gestalt` network.
//!
//! The scalar file layout and forward pass were certified independently against Viridithas v13
//! before this module was added. This module keeps the same mathematics while adding a reversible
//! search-side accumulator: ordinary moves touch only a handful of feature rows, and a king move
//! rebuilds only the perspective whose mirrored king bucket changed.
//!
//! This is deliberately separate from [`crate::evaluate`]. Production remains on the accepted
//! classical evaluator until this research path earns strength under the repository SPRT protocol.

use std::{fs, path::Path};

use chess_core::{ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square};

pub const INPUTS: usize = 768;
pub const HIDDEN: usize = 1_536;
pub const BUCKETS: usize = 9;
pub const SERIALIZED_BYTES: usize = 21_242_944;

const QA: i32 = 255;
const QB: i32 = 64;
const SCALE: i32 = 400;
const FEATURE_WEIGHTS: usize = INPUTS * HIDDEN * BUCKETS;
const OUTPUT_WEIGHTS: usize = HIDDEN * 2;
const PAYLOAD_BYTES: usize = (FEATURE_WEIGHTS + HIDDEN + OUTPUT_WEIGHTS + 1) * 2;
const MAX_DELTA_FEATURES: usize = 4;

#[rustfmt::skip]
const BUCKET_MAP: [u8; 64] = [
     0,  1,  2,  3, 12, 11, 10,  9,
     4,  4,  5,  5, 14, 14, 13, 13,
     6,  6,  6,  6, 15, 15, 15, 15,
     7,  7,  7,  7, 16, 16, 16, 16,
     8,  8,  8,  8, 17, 17, 17, 17,
     8,  8,  8,  8, 17, 17, 17, 17,
     8,  8,  8,  8, 17, 17, 17, 17,
     8,  8,  8,  8, 17, 17, 17, 17,
];

/// Exact quantised `gestalt` parameters.
///
/// Weight storage is feature-major within each of the nine physical parameter buckets, matching the
/// certified v13 layout. Loading is an engine-setup operation; no filesystem work occurs in search.
pub struct Network {
    feature_weights: Box<[i16]>,
    feature_bias: Box<[i16]>,
    output_weights: Box<[i16]>,
    output_bias: i16,
}

impl Network {
    /// Parse the exact v13 `gestalt` binary representation.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() != SERIALIZED_BYTES {
            return Err(format!(
                "gestalt network size mismatch: expected {SERIALIZED_BYTES}, got {}",
                bytes.len()
            ));
        }

        let mut cursor = 0usize;
        let feature_weights = read_i16s(bytes, &mut cursor, FEATURE_WEIGHTS)?;
        let feature_bias = read_i16s(bytes, &mut cursor, HIDDEN)?;
        let output_weights = read_i16s(bytes, &mut cursor, OUTPUT_WEIGHTS)?;
        let output_bias = read_i16s(bytes, &mut cursor, 1)?[0];
        if cursor != PAYLOAD_BYTES || bytes.len().saturating_sub(cursor) != 62 {
            return Err(format!(
                "unexpected gestalt payload/alignment: payload={cursor}, trailing={}",
                bytes.len().saturating_sub(cursor)
            ));
        }

        Ok(Self {
            feature_weights,
            feature_bias,
            output_weights,
            output_bias,
        })
    }

    /// Load and parse a network at explicit engine setup time.
    pub fn from_file(path: &Path) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|error| format!("read {}: {error}", path.display()))?;
        Self::from_bytes(&bytes)
    }

    /// Slow full-refresh oracle used to certify incremental state.
    #[must_use]
    pub fn evaluate_full(&self, position: &Position) -> Option<i32> {
        let state = AccumulatorState::from_position(self, position)?;
        Some(state.evaluate(self, position.side_to_move()))
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

    fn apply_feature(
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

    fn score_accumulators(
        &self,
        white: &[i16; HIDDEN],
        black: &[i16; HIDDEN],
        side_to_move: Color,
    ) -> i32 {
        let (us, them) = match side_to_move {
            Color::White => (white, black),
            Color::Black => (black, white),
        };
        let mut output = 0_i64;
        for (index, &value) in us.iter().enumerate() {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[index]);
        }
        for (index, &value) in them.iter().enumerate() {
            let clipped = i64::from(i32::from(value).clamp(0, QA));
            output += clipped * clipped * i64::from(self.output_weights[HIDDEN + index]);
        }
        output /= i64::from(QA);
        output += i64::from(self.output_bias);
        output *= i64::from(SCALE);
        output /= i64::from(QA * QB);
        i32::try_from(output).expect("gestalt quantised output remains within i32")
    }
}

/// Perspective coordinate frame. `bucket` selects physical weights; `mirror_files` distinguishes the
/// paired raw v13 buckets that share weights but use opposite horizontal orientation.
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

/// Bounded move-derived update retained across recursive search.
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

/// Reversible two-perspective hidden state for one network.
///
/// This state is derived cache, never chess truth. It may always be discarded and rebuilt from the
/// current `Position`. Ordinary push/pop operations allocate nothing and copy no full accumulator.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AccumulatorState {
    white: PerspectiveAccumulator,
    black: PerspectiveAccumulator,
}

impl AccumulatorState {
    /// Build both perspective accumulators once at a search root.
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

    /// Derive the sparse update before making a generated legal move.
    #[must_use]
    pub fn prepare_move(position: &Position, mv: ChessMove) -> Option<PreparedAccumulatorUpdate> {
        Some(PreparedAccumulatorUpdate {
            white: prepare_perspective(position, mv, Color::White)?,
            black: prepare_perspective(position, mv, Color::Black)?,
        })
    }

    /// Advance after the caller has made the prepared move.
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

    /// Restore after the caller has unmade the prepared move.
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

    /// Evaluate the already-materialised state from side-to-move perspective.
    #[must_use]
    pub fn evaluate(&self, network: &Network, side_to_move: Color) -> i32 {
        network.score_accumulators(&self.white.values, &self.black.values, side_to_move)
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
            let rebuilt =
                network.rebuild_perspective(position, perspective, &mut accumulator.values)?;
            if !reverse {
                debug_assert_eq!(rebuilt, expected_child);
            }
            accumulator.frame = rebuilt;
        }
        PerspectiveUpdate::Delta(delta) => {
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
    }
    Some(())
}

#[derive(Clone, Copy)]
enum Direction {
    Add,
    Subtract,
}

fn frame_for_king(perspective: Color, king: Square) -> Frame {
    let map_square = match perspective {
        Color::White => king,
        Color::Black => flip_rank(king),
    };
    let raw = BUCKET_MAP[usize::from(map_square.index())];
    Frame {
        bucket: raw % BUCKETS as u8,
        mirror_files: king.file() >= 4,
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
        .ok_or_else(|| "gestalt field length overflow".to_owned())?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or_else(|| "gestalt cursor overflow".to_owned())?;
    let slice = bytes
        .get(*cursor..end)
        .ok_or_else(|| "truncated gestalt payload".to_owned())?;
    let (pairs, remainder) = slice.as_chunks::<2>();
    if !remainder.is_empty() {
        return Err("odd gestalt i16 field length".to_owned());
    }
    let values = pairs
        .iter()
        .map(|pair| i16::from_le_bytes(*pair))
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
    fn prepared_update_is_small_stack_state() {
        assert!(size_of::<PreparedAccumulatorUpdate>() <= 64);
    }

    #[test]
    fn incremental_push_pop_matches_full_refresh_across_long_play() {
        let network = patterned_network();
        let root = Position::startpos();
        let mut position = root.clone();
        let mut state = AccumulatorState::from_position(&network, &position).expect("legal root");
        assert_matches(&network, &state, &position);

        let original_state = state.clone();
        let mut history = Vec::new();
        for ply in 0..128_usize {
            let moves = position.legal_moves();
            if moves.is_empty() {
                break;
            }
            let mv = moves[(ply.wrapping_mul(29).wrapping_add(11)) % moves.len()];
            let prepared =
                AccumulatorState::prepare_move(&position, mv).expect("prepared legal move");
            let undo = position.make_move(mv);
            state
                .apply_prepared(&network, &position, prepared)
                .expect("apply child");
            assert_matches(&network, &state, &position);
            history.push((mv, undo, prepared));
        }

        while let Some((mv, undo, prepared)) = history.pop() {
            position.unmake_move(mv, undo);
            state
                .restore_after_unmake(&network, &position, prepared)
                .expect("restore parent");
            assert_matches(&network, &state, &position);
        }
        assert_eq!(position, root);
        assert_eq!(state, original_state);
    }

    #[test]
    fn special_moves_and_bucket_refresh_round_trip_exactly() {
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
        assert_matches(network, &state, &position);
        position.unmake_move(mv, undo);
        state
            .restore_after_unmake(network, &position, prepared)
            .expect("restore");
        assert_eq!(position, root);
        assert_eq!(state, root_state);
        assert_matches(network, &state, &position);
    }

    fn assert_matches(network: &Network, state: &AccumulatorState, position: &Position) {
        let full = network.evaluate_full(position).expect("full evaluator");
        assert_eq!(state.evaluate(network, position.side_to_move()), full);
    }

    fn patterned_network() -> Network {
        let mut feature_weights = vec![0_i16; FEATURE_WEIGHTS].into_boxed_slice();
        for (index, weight) in feature_weights.iter_mut().enumerate() {
            *weight = (index % 7) as i16 - 3;
        }
        let mut feature_bias = vec![0_i16; HIDDEN].into_boxed_slice();
        for (index, bias) in feature_bias.iter_mut().enumerate() {
            *bias = 96 + (index % 11) as i16 - 5;
        }
        let mut output_weights = vec![0_i16; OUTPUT_WEIGHTS].into_boxed_slice();
        for (index, weight) in output_weights.iter_mut().enumerate() {
            *weight = (index % 9) as i16 - 4;
        }
        Network {
            feature_weights,
            feature_bias,
            output_weights,
            output_bias: 17,
        }
    }
}
