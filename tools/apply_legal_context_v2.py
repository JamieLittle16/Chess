#!/usr/bin/env python3
"""Apply legality-context v2 over accepted mutation-free legality filtering.

The candidate preserves pseudo generation and exact move order. It computes checkers, absolute pins
and the single-check evasion mask once per move-generation call. Ordinary non-king/non-EP candidates
can then be admitted with cheap mask tests; only king moves/castles and en-passant retain the full
post-candidate attack reconstruction.
"""

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
    "    let pseudo = generate_pseudo_legal_moves(position);\n"
    "    pseudo\n"
    "        .iter()\n"
    "        .copied()\n"
    "        .any(|mv| candidate_keeps_king_safe(position, mv, us))\n",
    "    let Some(context) = legality_context(position, us) else {\n"
    "        return false;\n"
    "    };\n"
    "    let pseudo = generate_pseudo_legal_moves(position);\n"
    "    pseudo\n"
    "        .iter()\n"
    "        .copied()\n"
    "        .any(|mv| candidate_is_legal_with_context(position, mv, us, context))\n",
    "legal existence context",
)

text = replace_once(
    text,
    "fn filter_legal_moves(position: &mut Position, pseudo: &MoveList, us: Color) -> MoveList {\n"
    "    let mut legal = MoveList::new();\n"
    "    for &mv in pseudo {\n"
    "        if candidate_keeps_king_safe(position, mv, us) {\n"
    "            legal.push(mv);\n"
    "        }\n"
    "    }\n"
    "    legal\n"
    "}\n\n"
    "/// Test final king safety for a structurally valid generated candidate without mutating `position`.\n",
    "fn filter_legal_moves(position: &mut Position, pseudo: &MoveList, us: Color) -> MoveList {\n"
    "    let Some(context) = legality_context(position, us) else {\n"
    "        return MoveList::new();\n"
    "    };\n"
    "    let mut legal = MoveList::new();\n"
    "    for &mv in pseudo {\n"
    "        if candidate_is_legal_with_context(position, mv, us, context) {\n"
    "            legal.push(mv);\n"
    "        }\n"
    "    }\n"
    "    legal\n"
    "}\n\n"
    "#[derive(Clone, Copy, Debug)]\n"
    "struct LegalityContext {\n"
    "    king: Square,\n"
    "    check_count: u8,\n"
    "    evasion_mask: Bitboard,\n"
    "    pinned: Bitboard,\n"
    "}\n\n"
    "/// Build king-safety facts shared by every candidate at this node.\n"
    "///\n"
    "/// The accepted v1 filter reconstructed attacks after every pseudo-legal candidate. Most moves\n"
    "/// do not need that work: an ordinary move is king-safe iff it resolves the current single\n"
    "/// check (if any) and an absolutely pinned mover stays on its pin line. King moves and\n"
    "/// en-passant remain on the exact v1 post-candidate oracle because they alter attack geometry in\n"
    "/// ways not represented by those two masks.\n"
    "#[inline]\n"
    "fn legality_context(position: &Position, us: Color) -> Option<LegalityContext> {\n"
    "    let king = position.king_square(us)?;\n"
    "    let them = us.opposite();\n"
    "    let occupied = position.occupied();\n"
    "    let friendly = position.occupancy(us);\n\n"
    "    let enemy_bishops_queens =\n"
    "        position.pieces(them, PieceKind::Bishop) | position.pieces(them, PieceKind::Queen);\n"
    "    let enemy_rooks_queens =\n"
    "        position.pieces(them, PieceKind::Rook) | position.pieces(them, PieceKind::Queen);\n\n"
    "    let mut checkers = pawn_attacks(us, king) & position.pieces(them, PieceKind::Pawn);\n"
    "    checkers = checkers | (knight_attacks(king) & position.pieces(them, PieceKind::Knight));\n"
    "    checkers = checkers | (king_attacks(king) & position.pieces(them, PieceKind::King));\n"
    "    checkers = checkers | (bishop_attacks(king, occupied) & enemy_bishops_queens);\n"
    "    checkers = checkers | (rook_attacks(king, occupied) & enemy_rooks_queens);\n\n"
    "    // Remove our pieces only for the x-ray query. Any enemy non-slider before a potential\n"
    "    // pinner remains a blocker. A slider is an absolute pinner exactly when one friendly piece\n"
    "    // lies strictly between it and our king.\n"
    "    let xray_occupied = occupied & !friendly;\n"
    "    let bishop_pinners = bishop_attacks(king, xray_occupied) & enemy_bishops_queens;\n"
    "    let rook_pinners = rook_attacks(king, xray_occupied) & enemy_rooks_queens;\n"
    "    let mut pinned = Bitboard::EMPTY;\n"
    "    for pinner in bishop_pinners | rook_pinners {\n"
    "        let blockers = between_squares(king, pinner) & friendly;\n"
    "        if blockers.count() == 1 {\n"
    "            pinned = pinned | blockers;\n"
    "        }\n"
    "    }\n\n"
    "    let check_count = checkers.count() as u8;\n"
    "    let evasion_mask = if check_count == 1 {\n"
    "        let checker = checkers\n"
    "            .into_iter()\n"
    "            .next()\n"
    "            .expect(\"one checker has one square\");\n"
    "        between_squares(king, checker).with(checker)\n"
    "    } else {\n"
    "        Bitboard::EMPTY\n"
    "    };\n\n"
    "    Some(LegalityContext {\n"
    "        king,\n"
    "        check_count,\n"
    "        evasion_mask,\n"
    "        pinned,\n"
    "    })\n"
    "}\n\n"
    "#[inline]\n"
    "fn candidate_is_legal_with_context(\n"
    "    position: &Position,\n"
    "    mv: ChessMove,\n"
    "    us: Color,\n"
    "    context: LegalityContext,\n"
    ") -> bool {\n"
    "    // King moves (including castles) change the king square, while en-passant removes a pawn\n"
    "    // from a square other than the destination. Keep v1's exact final-occupancy attack oracle\n"
    "    // for both classes. This also safely handles pathological EP check evasions.\n"
    "    if mv.from() == context.king || mv.kind() == MoveKind::EnPassant {\n"
    "        return candidate_keeps_king_safe(position, mv, us);\n"
    "    }\n\n"
    "    if context.check_count >= 2 {\n"
    "        return false;\n"
    "    }\n"
    "    if context.check_count == 1 && !context.evasion_mask.contains(mv.to()) {\n"
    "        return false;\n"
    "    }\n"
    "    if context.pinned.contains(mv.from())\n"
    "        && !squares_are_collinear(context.king, mv.from(), mv.to())\n"
    "    {\n"
    "        return false;\n"
    "    }\n"
    "    true\n"
    "}\n\n"
    "#[inline]\n"
    "fn squares_are_collinear(origin: Square, through: Square, target: Square) -> bool {\n"
    "    let through_file = i16::from(through.file()) - i16::from(origin.file());\n"
    "    let through_rank = i16::from(through.rank()) - i16::from(origin.rank());\n"
    "    let target_file = i16::from(target.file()) - i16::from(origin.file());\n"
    "    let target_rank = i16::from(target.rank()) - i16::from(origin.rank());\n"
    "    through_file * target_rank == through_rank * target_file\n"
    "}\n\n"
    "/// Squares strictly between two aligned squares, or empty when they are not queen-aligned.\n"
    "#[inline]\n"
    "fn between_squares(from: Square, to: Square) -> Bitboard {\n"
    "    let file_delta = to.file() as i8 - from.file() as i8;\n"
    "    let rank_delta = to.rank() as i8 - from.rank() as i8;\n"
    "    if file_delta != 0\n"
    "        && rank_delta != 0\n"
    "        && file_delta.unsigned_abs() != rank_delta.unsigned_abs()\n"
    "    {\n"
    "        return Bitboard::EMPTY;\n"
    "    }\n\n"
    "    let file_step = file_delta.signum();\n"
    "    let rank_step = rank_delta.signum();\n"
    "    let mut file = from.file() as i8 + file_step;\n"
    "    let mut rank = from.rank() as i8 + rank_step;\n"
    "    let target_file = to.file() as i8;\n"
    "    let target_rank = to.rank() as i8;\n"
    "    let mut between = Bitboard::EMPTY;\n"
    "    while file != target_file || rank != target_rank {\n"
    "        let square = Square::from_file_rank(file as u8, rank as u8)\n"
    "            .expect(\"aligned ray remains on board\");\n"
    "        between = between.with(square);\n"
    "        file += file_step;\n"
    "        rank += rank_step;\n"
    "    }\n"
    "    between\n"
    "}\n\n"
    "/// Test final king safety for a structurally valid generated candidate without mutating `position`.\n",
    "shared legality context",
)

# Expand the existing make/unmake oracle regression with explicit single/double-check positions.
text = replace_once(
    text,
    "            \"k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1\",\n"
    "            \"k7/8/8/4KPpr/8/8/8/8 w - g6 0 1\",\n",
    "            \"k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1\",\n"
    "            \"4k3/8/8/8/1b6/8/4r3/4K3 w - - 0 1\",\n"
    "            \"4k3/8/8/8/8/8/4r3/3BK3 w - - 0 1\",\n"
    "            \"k7/8/8/4KPpr/8/8/8/8 w - g6 0 1\",\n",
    "legality regression positions",
)

path.write_text(text)
