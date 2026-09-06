use crate::Position;

/// Count legal leaf nodes at `depth` using the correctness-first reference transition.
///
/// This is a validation oracle, not a search-performance primitive. M2 will add an optimized
/// make/unmake perft path and require it to match this function exactly.
#[must_use]
pub fn perft(position: &Position, depth: u32) -> u64 {
    if depth == 0 {
        return 1;
    }

    let moves = position.legal_moves();
    if depth == 1 {
        return moves.len() as u64;
    }

    let mut nodes = 0_u64;
    for &mv in &moves {
        let next = position
            .reference_after(mv)
            .expect("legal moves must have a valid reference transition");
        nodes = nodes.saturating_add(perft(&next, depth - 1));
    }
    nodes
}

#[cfg(test)]
mod tests {
    use crate::{perft, Position};

    #[test]
    fn initial_position_matches_reference_perft() {
        let position = Position::startpos();
        assert_eq!(perft(&position, 0), 1);
        assert_eq!(perft(&position, 1), 20);
        assert_eq!(perft(&position, 2), 400);
        assert_eq!(perft(&position, 3), 8_902);
        assert_eq!(perft(&position, 4), 197_281);
    }

    #[test]
    fn kiwipete_matches_reference_perft() {
        let position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid Kiwipete position");
        assert_eq!(perft(&position, 1), 48);
        assert_eq!(perft(&position, 2), 2_039);
        assert_eq!(perft(&position, 3), 97_862);
    }

    #[test]
    fn rook_and_en_passant_stress_position_matches_reference_perft() {
        let position = Position::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1")
            .expect("valid reference position");
        assert_eq!(perft(&position, 1), 14);
        assert_eq!(perft(&position, 2), 191);
        assert_eq!(perft(&position, 3), 2_812);
        assert_eq!(perft(&position, 4), 43_238);
    }
}
