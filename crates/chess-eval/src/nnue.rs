//! Versioned sparse king-relative feature substrate for learned evaluation research.
//!
//! This module does not change the production classical evaluator. It defines the first NNUE feature
//! identity and, crucially, a move-derived incremental update that can be checked against a complete
//! rebuild from `Position`. Neural weights and accumulators are deliberately deferred until this
//! representation is trustworthy.

use chess_core::{ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square};

/// Stable identifier for the first sparse learned-evaluation feature mapping.
pub const FEATURE_SET_ID: &str = "king-piece-v1";
/// Exact-rank, horizontally mirrored king buckets: 8 ranks x 4 canonical files.
pub const KING_BUCKETS: usize = 32;
/// Relative ownership (ours/theirs) x six piece kinds.
pub const PIECE_PLANES: usize = 12;
/// Total number of sparse input features.
pub const FEATURE_COUNT: usize = KING_BUCKETS * PIECE_PLANES * 64;
/// Maximum number of pieces in a legal chess position.
pub const MAX_ACTIVE_FEATURES: usize = 32;
const MAX_DELTA_FEATURES: usize = 4;

/// Compact index into the versioned sparse input feature table.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct FeatureIndex(u16);

impl FeatureIndex {
    /// Return the zero-based feature-table index.
    #[must_use]
    pub const fn raw(self) -> u16 {
        self.0
    }
}

/// Perspective-dependent coordinate frame used by the sparse feature mapper.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FeatureFrame {
    bucket: u8,
    mirror_files: bool,
}

impl FeatureFrame {
    /// Canonical king bucket in `0..KING_BUCKETS`.
    #[must_use]
    pub const fn bucket(self) -> u8 {
        self.bucket
    }

    /// Whether board files are horizontally mirrored in this frame.
    #[must_use]
    pub const fn mirrors_files(self) -> bool {
        self.mirror_files
    }
}

/// Complete active sparse features for one evaluation perspective.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FeatureSet {
    frame: FeatureFrame,
    indices: [FeatureIndex; MAX_ACTIVE_FEATURES],
    len: u8,
}

impl FeatureSet {
    /// Coordinate frame shared by every index in this set.
    #[must_use]
    pub const fn frame(&self) -> FeatureFrame {
        self.frame
    }

    /// Sorted active feature indices.
    #[must_use]
    pub fn as_slice(&self) -> &[FeatureIndex] {
        &self.indices[..usize::from(self.len)]
    }

    /// Number of active features.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.len as usize
    }

    /// Whether no features are active.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }
}

/// Small non-refresh feature update produced directly from one legal move.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FeatureDelta {
    removed: [FeatureIndex; MAX_DELTA_FEATURES],
    removed_len: u8,
    added: [FeatureIndex; MAX_DELTA_FEATURES],
    added_len: u8,
}

impl FeatureDelta {
    fn new() -> Self {
        Self {
            removed: [FeatureIndex(0); MAX_DELTA_FEATURES],
            removed_len: 0,
            added: [FeatureIndex(0); MAX_DELTA_FEATURES],
            added_len: 0,
        }
    }

    fn push_removed(&mut self, index: FeatureIndex) {
        let slot = usize::from(self.removed_len);
        debug_assert!(slot < MAX_DELTA_FEATURES);
        self.removed[slot] = index;
        self.removed_len += 1;
    }

    fn push_added(&mut self, index: FeatureIndex) {
        let slot = usize::from(self.added_len);
        debug_assert!(slot < MAX_DELTA_FEATURES);
        self.added[slot] = index;
        self.added_len += 1;
    }

    fn sort(&mut self) {
        self.removed[..usize::from(self.removed_len)].sort_unstable();
        self.added[..usize::from(self.added_len)].sort_unstable();
    }

    /// Features to subtract from an incremental accumulator.
    #[must_use]
    pub fn removed(&self) -> &[FeatureIndex] {
        &self.removed[..usize::from(self.removed_len)]
    }

    /// Features to add to an incremental accumulator.
    #[must_use]
    pub fn added(&self) -> &[FeatureIndex] {
        &self.added[..usize::from(self.added_len)]
    }
}

/// Incremental action required for one perspective after a move.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FeatureUpdate {
    /// The perspective king changed coordinate frame; rebuild that accumulator from the resulting
    /// position rather than attempting to rewrite every active feature individually.
    Refresh(FeatureFrame),
    /// The frame is unchanged and only these sparse features changed.
    Delta(FeatureDelta),
}

/// Rebuild all active sparse features for `perspective` directly from chess truth.
///
/// `None` is returned for malformed positions without the perspective king or with more than the
/// legal maximum of 32 pieces. Legal engine positions always produce a set.
#[must_use]
pub fn active_features(position: &Position, perspective: Color) -> Option<FeatureSet> {
    let king = position.king_square(perspective)?;
    let frame = frame_for_king(perspective, king);
    let mut set = FeatureSet {
        frame,
        indices: [FeatureIndex(0); MAX_ACTIVE_FEATURES],
        len: 0,
    };

    for color in Color::ALL {
        for kind in PieceKind::ALL {
            let piece = Piece::new(color, kind);
            for square in position.pieces(color, kind) {
                let slot = usize::from(set.len);
                if slot >= MAX_ACTIVE_FEATURES {
                    return None;
                }
                set.indices[slot] = feature_index(frame, perspective, piece, square);
                set.len += 1;
            }
        }
    }
    set.indices[..usize::from(set.len)].sort_unstable();
    Some(set)
}

/// Derive the sparse learned-evaluation update for `mv` without making the move.
///
/// The caller must supply a generated legal move. A perspective-king frame change returns
/// [`FeatureUpdate::Refresh`]; ordinary moves, captures, promotions, en-passant and opponent castling
/// return a bounded add/subtract delta suitable for a future hidden accumulator.
#[must_use]
pub fn feature_update_for_move(
    position: &Position,
    mv: ChessMove,
    perspective: Color,
) -> Option<FeatureUpdate> {
    let king = position.king_square(perspective)?;
    let frame = frame_for_king(perspective, king);
    let moving = position.piece_at(mv.from())?;

    if moving.color() == perspective && moving.kind() == PieceKind::King {
        let next_frame = frame_for_king(perspective, mv.to());
        if next_frame != frame {
            return Some(FeatureUpdate::Refresh(next_frame));
        }
    }

    let mut delta = FeatureDelta::new();
    delta.push_removed(feature_index(frame, perspective, moving, mv.from()));

    if let Some(captured_square) = captured_square(position, moving.color(), mv)
        && let Some(captured) = position.piece_at(captured_square)
    {
        delta.push_removed(feature_index(frame, perspective, captured, captured_square));
    }

    let resulting_piece = mv
        .kind()
        .promotion_piece()
        .map_or(moving, |kind| Piece::new(moving.color(), kind));
    delta.push_added(feature_index(frame, perspective, resulting_piece, mv.to()));

    if let Some((rook_from, rook_to)) = castle_rook_displacement(moving.color(), mv.kind()) {
        let rook = Piece::new(moving.color(), PieceKind::Rook);
        delta.push_removed(feature_index(frame, perspective, rook, rook_from));
        delta.push_added(feature_index(frame, perspective, rook, rook_to));
    }

    delta.sort();
    Some(FeatureUpdate::Delta(delta))
}

fn frame_for_king(perspective: Color, king: Square) -> FeatureFrame {
    let (file, rank) = perspective_relative_coordinates(perspective, king);
    let mirror_files = file >= 4;
    let canonical_file = if mirror_files { 7 - file } else { file };
    FeatureFrame {
        bucket: rank * 4 + canonical_file,
        mirror_files,
    }
}

fn feature_index(
    frame: FeatureFrame,
    perspective: Color,
    piece: Piece,
    square: Square,
) -> FeatureIndex {
    let ownership = if piece.color() == perspective { 0 } else { 1 };
    let plane = ownership * PieceKind::ALL.len() + piece.kind().index();
    let square = oriented_square(frame, perspective, square);
    let raw = usize::from(frame.bucket) * PIECE_PLANES * 64 + plane * 64 + square.index() as usize;
    debug_assert!(raw < FEATURE_COUNT);
    FeatureIndex(raw as u16)
}

fn oriented_square(frame: FeatureFrame, perspective: Color, square: Square) -> Square {
    let (mut file, rank) = perspective_relative_coordinates(perspective, square);
    if frame.mirror_files {
        file = 7 - file;
    }
    Square::from_file_rank(file, rank).expect("oriented board coordinates remain on board")
}

fn perspective_relative_coordinates(perspective: Color, square: Square) -> (u8, u8) {
    let rank = match perspective {
        Color::White => square.rank(),
        Color::Black => 7 - square.rank(),
    };
    (square.file(), rank)
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

fn square(file: u8, rank: u8) -> Square {
    Square::from_file_rank(file, rank).expect("constant board coordinate")
}

#[cfg(test)]
mod tests {
    use chess_core::{ChessMove, Color, MoveKind, Position, Square};

    use super::{
        FEATURE_COUNT, FeatureSet, FeatureUpdate, active_features, feature_update_for_move,
    };

    #[test]
    fn start_position_has_bounded_sorted_features_for_both_perspectives() {
        let position = Position::startpos();
        for perspective in Color::ALL {
            let features =
                active_features(&position, perspective).expect("start position has king");
            assert_eq!(features.len(), 32);
            assert!(features.as_slice().windows(2).all(|pair| pair[0] < pair[1]));
            assert!(
                features
                    .as_slice()
                    .iter()
                    .all(|index| usize::from(index.raw()) < FEATURE_COUNT)
            );
        }
    }

    #[test]
    fn color_swapped_vertical_mirror_has_identical_relative_features() {
        let white = Position::from_fen("4k3/8/8/8/8/8/3P4/4K3 w - - 0 1").expect("valid position");
        let black =
            Position::from_fen("4k3/3p4/8/8/8/8/8/4K3 b - - 0 1").expect("valid mirrored position");
        assert_eq!(
            active_features(&white, Color::White),
            active_features(&black, Color::Black)
        );
    }

    #[test]
    fn move_derived_updates_match_full_rebuild_across_deterministic_play() {
        let mut position = Position::startpos();
        for ply in 0..128_usize {
            let moves = position.legal_moves();
            if moves.is_empty() {
                break;
            }
            let mv = moves[(ply.wrapping_mul(17).wrapping_add(3)) % moves.len()];
            let white_before = active_features(&position, Color::White).expect("white king");
            let black_before = active_features(&position, Color::Black).expect("black king");
            let white_update =
                feature_update_for_move(&position, mv, Color::White).expect("white update");
            let black_update =
                feature_update_for_move(&position, mv, Color::Black).expect("black update");

            let _undo = position.make_move(mv);
            let white_after = active_features(&position, Color::White).expect("white king after");
            let black_after = active_features(&position, Color::Black).expect("black king after");
            assert_update_matches(white_before, white_after, white_update);
            assert_update_matches(black_before, black_after, black_update);
        }
    }

    #[test]
    fn special_moves_have_correct_sparse_updates() {
        assert_special_move(
            "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
            square(4, 0),
            square(6, 0),
            None,
        );
        assert_special_move(
            "k7/8/8/4KPpr/8/8/8/8 w - g6 0 1",
            square(5, 4),
            square(6, 5),
            None,
        );
        assert_special_move(
            "7k/P7/8/8/8/8/8/K7 w - - 0 1",
            square(0, 6),
            square(0, 7),
            Some(MoveKind::PromoteQueen),
        );
    }

    fn assert_special_move(fen: &str, from: Square, to: Square, required_kind: Option<MoveKind>) {
        let mut position = Position::from_fen(fen).expect("valid special position");
        let mv = find_move(&position, from, to, required_kind);
        for perspective in Color::ALL {
            let before = active_features(&position, perspective).expect("king before");
            let update =
                feature_update_for_move(&position, mv, perspective).expect("feature update");
            let undo = position.make_move(mv);
            let after = active_features(&position, perspective).expect("king after");
            position.unmake_move(mv, undo);
            assert_update_matches(before, after, update);
        }
    }

    fn find_move(
        position: &Position,
        from: Square,
        to: Square,
        required_kind: Option<MoveKind>,
    ) -> ChessMove {
        position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| {
                mv.from() == from
                    && mv.to() == to
                    && required_kind.is_none_or(|kind| mv.kind() == kind)
            })
            .expect("requested special move is legal")
    }

    fn assert_update_matches(before: FeatureSet, after: FeatureSet, update: FeatureUpdate) {
        match update {
            FeatureUpdate::Refresh(frame) => assert_eq!(frame, after.frame()),
            FeatureUpdate::Delta(delta) => {
                assert_eq!(before.frame(), after.frame());
                let mut rebuilt = before.as_slice().to_vec();
                for removed in delta.removed() {
                    let index = rebuilt
                        .iter()
                        .position(|candidate| candidate == removed)
                        .expect("removed feature was active");
                    rebuilt.remove(index);
                }
                rebuilt.extend_from_slice(delta.added());
                rebuilt.sort_unstable();
                assert_eq!(rebuilt.as_slice(), after.as_slice());
            }
        }
    }

    fn square(file: u8, rank: u8) -> Square {
        Square::from_file_rank(file, rank).expect("constant board coordinate")
    }
}
