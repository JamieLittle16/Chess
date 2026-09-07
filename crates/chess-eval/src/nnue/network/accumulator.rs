//! Reversible fixed-capacity hidden accumulators for `king-piece-v1` NNUE networks.
//!
//! This is still a correctness substrate, not a production evaluator switch. Search can eventually
//! keep one `AccumulatorState` beside its reversible `Position`, but NNUE scores remain outside the
//! production search until a trained model earns equal-time Elo.

use chess_core::{ChessMove, Color, Position};

use super::super::{FeatureDelta, FeatureFrame, FeatureUpdate, feature_update_for_move};
use super::{MAX_HIDDEN, Network};

/// The two perspective-specific sparse updates implied by one legal chess move.
///
/// This is intentionally `Copy` and bounded so search can retain it as an ordinary stack local across
/// a recursive make/search/unmake sequence. It contains no hidden accumulator copy and no heap state.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PreparedAccumulatorUpdate {
    white: FeatureUpdate,
    black: FeatureUpdate,
}

/// One perspective's king-relative hidden accumulator.
#[derive(Clone, Debug, PartialEq, Eq)]
struct PerspectiveAccumulator {
    frame: FeatureFrame,
    values: [i32; MAX_HIDDEN],
}

/// Reconstructible learned-evaluation cache for both board perspectives.
///
/// The state is derived from `Position` and a particular `Network`; it is never chess truth. A caller
/// may discard and rebuild it at any time. Ordinary moves update only a handful of weight rows. When
/// the relevant king changes feature frame, only that perspective is fully refreshed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AccumulatorState {
    white: PerspectiveAccumulator,
    black: PerspectiveAccumulator,
}

impl AccumulatorState {
    /// Rebuild both hidden accumulators directly from `position`.
    #[must_use]
    pub fn from_position(network: &Network, position: &Position) -> Option<Self> {
        let mut white = [0_i32; MAX_HIDDEN];
        let mut black = [0_i32; MAX_HIDDEN];
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

    /// Derive the bounded accumulator update before making `mv` on `position`.
    ///
    /// The caller must supply a generated legal move. The returned value can be retained unchanged
    /// across the recursive child search and then reused to restore the accumulator after unmake.
    #[must_use]
    pub fn prepare_move(position: &Position, mv: ChessMove) -> Option<PreparedAccumulatorUpdate> {
        Some(PreparedAccumulatorUpdate {
            white: feature_update_for_move(position, mv, Color::White)?,
            black: feature_update_for_move(position, mv, Color::Black)?,
        })
    }

    /// Advance this state after the caller has made the move associated with `prepared`.
    ///
    /// `position_after` must be the resulting legal position. Refresh markers rebuild only the
    /// perspective whose king frame changed; delta updates touch only changed feature rows.
    pub fn apply_prepared(
        &mut self,
        network: &Network,
        position_after: &Position,
        prepared: PreparedAccumulatorUpdate,
    ) -> Option<()> {
        Self::apply_one(
            &mut self.white,
            network,
            position_after,
            Color::White,
            prepared.white,
            Direction::Forward,
        )?;
        Self::apply_one(
            &mut self.black,
            network,
            position_after,
            Color::Black,
            prepared.black,
            Direction::Forward,
        )?;
        Some(())
    }

    /// Restore this state after the caller has unmade the move associated with `prepared`.
    ///
    /// Ordinary deltas are algebraically inverted. A perspective that refreshed on the forward king
    /// move is rebuilt from the restored parent position; no full accumulator snapshot is required.
    pub fn restore_after_unmake(
        &mut self,
        network: &Network,
        restored_position: &Position,
        prepared: PreparedAccumulatorUpdate,
    ) -> Option<()> {
        Self::apply_one(
            &mut self.white,
            network,
            restored_position,
            Color::White,
            prepared.white,
            Direction::Reverse,
        )?;
        Self::apply_one(
            &mut self.black,
            network,
            restored_position,
            Color::Black,
            prepared.black,
            Direction::Reverse,
        )?;
        Some(())
    }

    /// Score the already-built accumulators from `side_to_move`'s perspective.
    #[must_use]
    pub fn evaluate(&self, network: &Network, side_to_move: Color) -> i32 {
        network.score_accumulators(&self.white.values, &self.black.values, side_to_move)
    }

    /// Current feature frame for one perspective, primarily useful to assert refresh behavior.
    #[must_use]
    pub const fn frame(&self, perspective: Color) -> FeatureFrame {
        match perspective {
            Color::White => self.white.frame,
            Color::Black => self.black.frame,
        }
    }

    fn apply_one(
        accumulator: &mut PerspectiveAccumulator,
        network: &Network,
        position: &Position,
        perspective: Color,
        update: FeatureUpdate,
        direction: Direction,
    ) -> Option<()> {
        match update {
            FeatureUpdate::Refresh(expected_after) => {
                let rebuilt =
                    network.rebuild_perspective(position, perspective, &mut accumulator.values)?;
                if direction == Direction::Forward {
                    debug_assert_eq!(rebuilt, expected_after);
                }
                accumulator.frame = rebuilt;
            }
            FeatureUpdate::Delta(delta) => {
                Self::apply_delta(network, &mut accumulator.values, delta, direction);
            }
        }
        Some(())
    }

    fn apply_delta(
        network: &Network,
        values: &mut [i32; MAX_HIDDEN],
        delta: FeatureDelta,
        direction: Direction,
    ) {
        match direction {
            Direction::Forward => {
                for &feature in delta.removed() {
                    network.apply_feature_row(values, feature, -1);
                }
                for &feature in delta.added() {
                    network.apply_feature_row(values, feature, 1);
                }
            }
            Direction::Reverse => {
                for &feature in delta.added() {
                    network.apply_feature_row(values, feature, -1);
                }
                for &feature in delta.removed() {
                    network.apply_feature_row(values, feature, 1);
                }
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Direction {
    Forward,
    Reverse,
}

#[cfg(test)]
mod tests {
    use std::mem::size_of;

    use chess_core::{ChessMove, Color, MoveKind, Position, Square};

    use super::super::{
        FEATURE_COUNT, FORMAT_VERSION, HEADER_LEN, MAGIC, encoded_feature_id, payload_checksum,
        payload_len_for,
    };
    use super::*;

    #[test]
    fn prepared_update_is_small_fixed_stack_state() {
        assert!(size_of::<PreparedAccumulatorUpdate>() <= 64);
    }

    #[test]
    fn incremental_push_and_pop_match_full_oracle_across_long_legal_play() {
        let network = patterned_network();
        let root = Position::startpos();
        let mut position = root.clone();
        let mut accumulator =
            AccumulatorState::from_position(&network, &position).expect("legal root state");
        assert_matches_oracle(&network, &accumulator, &position);

        let mut history = Vec::new();
        for ply in 0..192_usize {
            let moves = position.legal_moves();
            if moves.is_empty() {
                break;
            }
            let mv = moves[(ply.wrapping_mul(29).wrapping_add(11)) % moves.len()];
            let prepared = AccumulatorState::prepare_move(&position, mv).expect("legal update");
            let undo = position.make_move(mv);
            accumulator
                .apply_prepared(&network, &position, prepared)
                .expect("legal child state");
            assert_matches_oracle(&network, &accumulator, &position);
            history.push((mv, undo, prepared));
        }

        while let Some((mv, undo, prepared)) = history.pop() {
            position.unmake_move(mv, undo);
            accumulator
                .restore_after_unmake(&network, &position, prepared)
                .expect("legal restored state");
            assert_matches_oracle(&network, &accumulator, &position);
        }
        assert_eq!(position, root);
    }

    #[test]
    fn special_moves_and_king_refresh_round_trip_exactly() {
        let network = patterned_network();
        assert_move_round_trip(
            &network,
            "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
            square(4, 0),
            square(6, 0),
            None,
            true,
        );
        assert_move_round_trip(
            &network,
            "k7/8/8/4KPp1/8/8/8/8 w - g6 0 1",
            square(5, 4),
            square(6, 5),
            None,
            false,
        );
        assert_move_round_trip(
            &network,
            "7k/P7/8/8/8/8/8/K7 w - - 0 1",
            square(0, 6),
            square(0, 7),
            Some(MoveKind::PromoteQueen),
            false,
        );
        assert_move_round_trip(
            &network,
            "7k/8/8/8/8/8/8/4K3 w - - 0 1",
            square(4, 0),
            square(5, 0),
            None,
            true,
        );
    }

    fn assert_move_round_trip(
        network: &Network,
        fen: &str,
        from: Square,
        to: Square,
        kind: Option<MoveKind>,
        expect_white_refresh: bool,
    ) {
        let mut position = Position::from_fen(fen).expect("valid special FEN");
        let original = position.clone();
        let mv = find_move(&position, from, to, kind);
        let mut accumulator =
            AccumulatorState::from_position(network, &position).expect("initial accumulator");
        let original_accumulator = accumulator.clone();
        let original_frame = accumulator.frame(Color::White);
        let prepared = AccumulatorState::prepare_move(&position, mv).expect("prepared update");
        let undo = position.make_move(mv);
        accumulator
            .apply_prepared(network, &position, prepared)
            .expect("applied update");
        assert_matches_oracle(network, &accumulator, &position);
        if expect_white_refresh {
            assert_ne!(accumulator.frame(Color::White), original_frame);
        }

        position.unmake_move(mv, undo);
        accumulator
            .restore_after_unmake(network, &position, prepared)
            .expect("restored update");
        assert_eq!(position, original);
        assert_eq!(accumulator, original_accumulator);
        assert_matches_oracle(network, &accumulator, &position);
    }

    fn find_move(
        position: &Position,
        from: Square,
        to: Square,
        kind: Option<MoveKind>,
    ) -> ChessMove {
        position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| {
                mv.from() == from
                    && mv.to() == to
                    && kind.is_none_or(|required| mv.kind() == required)
            })
            .expect("requested move is legal")
    }

    fn assert_matches_oracle(
        network: &Network,
        accumulator: &AccumulatorState,
        position: &Position,
    ) {
        assert_eq!(
            Some(accumulator.evaluate(network, position.side_to_move())),
            network.evaluate_full(position)
        );
    }

    fn patterned_network() -> Network {
        let hidden = 32_usize;
        let payload_len = payload_len_for(hidden).expect("tiny payload fits");
        let mut payload = Vec::with_capacity(payload_len);

        for neuron in 0..hidden {
            let bias = 64_i16 + (neuron as i16 % 7) - 3;
            payload.extend_from_slice(&bias.to_le_bytes());
        }
        for feature in 0..FEATURE_COUNT {
            for neuron in 0..hidden {
                let value = ((feature * 7 + neuron * 3) % 5) as i16 - 2;
                payload.extend_from_slice(&value.to_le_bytes());
            }
        }
        for neuron in 0..(hidden * 2) {
            let value = ((neuron * 5 + 1) % 9) as i16 - 4;
            payload.extend_from_slice(&value.to_le_bytes());
        }
        payload.extend_from_slice(&17_i32.to_le_bytes());
        assert_eq!(payload.len(), payload_len);

        let mut bytes = Vec::with_capacity(HEADER_LEN + payload_len);
        bytes.extend_from_slice(&MAGIC);
        bytes.extend_from_slice(&FORMAT_VERSION.to_le_bytes());
        bytes.extend_from_slice(&encoded_feature_id());
        bytes.extend_from_slice(&(FEATURE_COUNT as u32).to_le_bytes());
        bytes.extend_from_slice(&(hidden as u16).to_le_bytes());
        bytes.extend_from_slice(&127_i16.to_le_bytes());
        bytes.extend_from_slice(&8_i32.to_le_bytes());
        bytes.extend_from_slice(&(payload_len as u32).to_le_bytes());
        bytes.extend_from_slice(&payload_checksum(&payload).to_le_bytes());
        bytes.extend_from_slice(&[9_u8; 32]);
        assert_eq!(bytes.len(), HEADER_LEN);
        bytes.extend_from_slice(&payload);

        Network::from_bytes(&bytes).expect("patterned test network is valid")
    }

    fn square(file: u8, rank: u8) -> Square {
        Square::from_file_rank(file, rank).expect("constant board coordinate")
    }
}
