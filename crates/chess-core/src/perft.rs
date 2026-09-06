use crate::{Position, generate_legal_moves_mut};

/// Count legal leaf nodes at `depth` while leaving `position` unchanged.
///
/// This convenience entry point clones the root once. Recursive work uses the reversible position
/// transition rather than allocating or cloning a position per child.
#[must_use]
pub fn perft(position: &Position, depth: u32) -> u64 {
    if depth == 0 {
        return 1;
    }
    let mut scratch = position.clone();
    perft_mut(&mut scratch, depth)
}

/// In-place perft for validation and performance measurement.
///
/// The supplied position is restored exactly before return.
#[must_use]
pub fn perft_mut(position: &mut Position, depth: u32) -> u64 {
    if depth == 0 {
        return 1;
    }

    let moves = generate_legal_moves_mut(position);
    if depth == 1 {
        return moves.len() as u64;
    }

    let mut nodes = 0_u64;
    for &mv in &moves {
        let undo = position.make_move(mv);
        nodes = nodes.saturating_add(perft_mut(position, depth - 1));
        position.unmake_move(mv, undo);
    }
    nodes
}

#[cfg(test)]
mod tests {
    use crate::{Position, perft, perft_mut};

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

    #[test]
    fn in_place_perft_restores_root_exactly() {
        let mut position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid Kiwipete position");
        let before = position.clone();
        assert_eq!(perft_mut(&mut position, 3), 97_862);
        assert_eq!(position, before);
    }
}
