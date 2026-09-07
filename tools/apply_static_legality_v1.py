#!/usr/bin/env python3
"""Replace make/unmake legality filtering with mutation-free post-move attack tests."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-core/src/movegen.rs")
text = path.read_text()

text = replace_once(
    text,
    '''    let pseudo = generate_pseudo_legal_moves(position);
    for &mv in &pseudo {
        let undo = position.make_move(mv);
        let is_legal = position
            .king_square(us)
            .is_some_and(|king| !is_square_attacked(position, king, us.opposite()));
        position.unmake_move(mv, undo);
        if is_legal {
            return true;
        }
    }
    false
}''',
    '''    let pseudo = generate_pseudo_legal_moves(position);
    pseudo
        .iter()
        .copied()
        .any(|mv| candidate_keeps_king_safe(position, mv, us))
}''',
    "early legal existence filter",
)

text = replace_once(
    text,
    '''fn filter_legal_moves(position: &mut Position, pseudo: &MoveList, us: Color) -> MoveList {
    let mut legal = MoveList::new();
    for &mv in pseudo {
        let undo = position.make_move(mv);
        let is_legal = position
            .king_square(us)
            .is_some_and(|king| !is_square_attacked(position, king, us.opposite()));
        position.unmake_move(mv, undo);
        if is_legal {
            legal.push(mv);
        }
    }
    legal
}''',
    '''fn filter_legal_moves(position: &mut Position, pseudo: &MoveList, us: Color) -> MoveList {
    let mut legal = MoveList::new();
    for &mv in pseudo {
        if candidate_keeps_king_safe(position, mv, us) {
            legal.push(mv);
        }
    }
    legal
}

/// Test final king safety for a structurally valid generated candidate without mutating `position`.
///
/// Legality filtering only needs the resulting occupancy, resulting king square, and the opponent
/// piece masks after any capture. This avoids updating/restoring clocks, castling rights, en-passant
/// state and Zobrist keys merely to answer whether our king is attacked. The pseudo generator has
/// already validated move geometry and castling's start/transit squares.
#[inline]
fn candidate_keeps_king_safe(position: &Position, mv: ChessMove, us: Color) -> bool {
    let Some(moving) = position.piece_at(mv.from()) else {
        return false;
    };
    debug_assert_eq!(moving.color(), us);

    let captured = captured_square_for_candidate(us, mv);
    let mut occupied = position.occupied().without(mv.from());
    if let Some(square) = captured {
        occupied = occupied.without(square);
    }

    if let Some((rook_from, rook_to)) = castle_rook_displacement(us, mv.kind()) {
        occupied = occupied.without(rook_from).with(rook_to);
    }
    occupied = occupied.with(mv.to());

    let king = if moving.kind() == PieceKind::King {
        mv.to()
    } else {
        let Some(king) = position.king_square(us) else {
            return false;
        };
        king
    };

    !is_square_attacked_after_candidate(position, king, us.opposite(), occupied, captured)
}

#[inline]
fn is_square_attacked_after_candidate(
    position: &Position,
    square: Square,
    attacker: Color,
    occupied: Bitboard,
    captured: Option<Square>,
) -> bool {
    let survivors = |kind| {
        let pieces = position.pieces(attacker, kind);
        captured.map_or(pieces, |square| pieces.without(square))
    };

    if !(pawn_attacks(attacker.opposite(), square) & survivors(PieceKind::Pawn)).is_empty() {
        return true;
    }
    if !(knight_attacks(square) & survivors(PieceKind::Knight)).is_empty() {
        return true;
    }
    if !(king_attacks(square) & survivors(PieceKind::King)).is_empty() {
        return true;
    }

    let bishops_and_queens = survivors(PieceKind::Bishop) | survivors(PieceKind::Queen);
    if !(bishop_attacks(square, occupied) & bishops_and_queens).is_empty() {
        return true;
    }

    let rooks_and_queens = survivors(PieceKind::Rook) | survivors(PieceKind::Queen);
    !(rook_attacks(square, occupied) & rooks_and_queens).is_empty()
}

#[inline]
fn captured_square_for_candidate(us: Color, mv: ChessMove) -> Option<Square> {
    if mv.kind() == MoveKind::EnPassant {
        let rank = match us {
            Color::White => mv.to().rank().checked_sub(1)?,
            Color::Black => mv.to().rank().checked_add(1)?,
        };
        Square::from_file_rank(mv.to().file(), rank)
    } else if mv.kind().is_capture() {
        Some(mv.to())
    } else {
        None
    }
}

#[inline]
fn castle_rook_displacement(us: Color, kind: MoveKind) -> Option<(Square, Square)> {
    let rank = match us {
        Color::White => 0,
        Color::Black => 7,
    };
    match kind {
        MoveKind::KingCastle => Some((square(7, rank), square(5, rank))),
        MoveKind::QueenCastle => Some((square(0, rank), square(3, rank))),
        _ => None,
    }
}''',
    "mutation-free legality filter",
)

text = replace_once(
    text,
    '''    #[test]
    fn castling_moves_are_generated_when_paths_are_safe() {''',
    '''    #[test]
    fn static_legality_filter_matches_make_unmake_reference_in_order() {
        let fens = [
            crate::STARTPOS_FEN,
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
            "k7/8/8/4KPpr/8/8/8/8 w - g6 0 1",
            "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
            "7k/P7/8/8/8/8/8/K7 w - - 0 1",
        ];

        for fen in fens {
            let mut position = Position::from_fen(fen).expect("valid legality FEN");
            assert_static_filter_matches_reference(&mut position, fen);
        }

        let mut position = Position::startpos();
        for ply in 0..96_usize {
            assert_static_filter_matches_reference(&mut position, "deterministic playout");
            let moves = reference_legal_moves(&mut position);
            if moves.is_empty() {
                break;
            }
            let mv = moves[(ply.wrapping_mul(17).wrapping_add(3)) % moves.len()];
            let _undo = position.make_move(mv);
        }
    }

    fn assert_static_filter_matches_reference(position: &mut Position, label: &str) {
        let original = position.clone();
        let actual = generate_legal_moves_mut(position);
        assert_eq!(*position, original, "static generator must not mutate {label}");
        let expected = reference_legal_moves(position);
        assert_eq!(actual.as_slice(), expected.as_slice(), "ordered legal mismatch for {label}");
        assert_eq!(*position, original, "reference filter must restore {label}");
    }

    fn reference_legal_moves(position: &mut Position) -> Vec<crate::ChessMove> {
        let us = position.side_to_move();
        let pseudo = super::generate_pseudo_legal_moves(position);
        let mut legal = Vec::new();
        for &mv in &pseudo {
            let undo = position.make_move(mv);
            let safe = !position.is_in_check(us);
            position.unmake_move(mv, undo);
            if safe {
                legal.push(mv);
            }
        }
        legal
    }

    #[test]
    fn castling_moves_are_generated_when_paths_are_safe() {''',
    "static legality differential tests",
)

path.write_text(text)
