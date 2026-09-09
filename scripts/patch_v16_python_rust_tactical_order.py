#!/usr/bin/env python3
"""Align Python's tactical ordering formula with production Rust V15.

TT priority and quiet/killers/history ordering remain unchanged. For captures/promotions only, use
Rust's ORDER_VALUES=(100,320,330,500,900,20000), capture=victim*32-attacker and
promotion=promoted*16. A common tactical base keeps every tactical ahead of killers while removing
Python's artificial capture-before-promotion band and destination-centre bias inside the stage.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='''    score = 0
    if target:
        score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])
    if promotion:
        score += 6_000_000 + int(PIECE_VALUE[promotion])
    if attacker == PAWN and target == 0 and not (move & FLAG_EP) and promotion == 0:
        signed_piece = int(board[from_square])
        raw_rank = to_square >> 3
        relative_rank = raw_rank if signed_piece > 0 else 7 - raw_rank
        if relative_rank == 6:
            # Only the immediate one-move promotion threat is special in V11. It searches just
            # ahead of generic killers, while sixth-rank pushes revert fully to ordinary quiets.
            # Tactical accuracy comes from the defender-safe horizon extension below, not optimism.
            score += 5_200_000
    score += int(ORDER_CENTER_BONUS[to_square])
    return score
'''
new='''    # Production Rust V15 tactical ordering, lifted into Python's existing score bands.
    # Keep a shared tactical base only to preserve the stage boundary versus killers/quiets.
    if target or promotion:
        score = 6_000_000
        if target:
            rust_victim = 100 if target == PAWN else (320 if target == KNIGHT else (330 if target == BISHOP else (500 if target == ROOK else (900 if target == QUEEN else 20_000))))
            rust_attacker = 100 if attacker == PAWN else (320 if attacker == KNIGHT else (330 if attacker == BISHOP else (500 if attacker == ROOK else (900 if attacker == QUEEN else 20_000))))
            score += 32 * rust_victim - rust_attacker
        if promotion:
            rust_promotion = 320 if promotion == KNIGHT else (330 if promotion == BISHOP else (500 if promotion == ROOK else 900))
            score += 16 * rust_promotion
        return score

    score = 0
    if attacker == PAWN and not (move & FLAG_EP):
        signed_piece = int(board[from_square])
        raw_rank = to_square >> 3
        relative_rank = raw_rank if signed_piece > 0 else 7 - raw_rank
        if relative_rank == 6:
            # Preserve Python's existing immediate-promotion-threat quiet heuristic; this lane only
            # changes tactical ordering.
            score += 5_200_000
    score += int(ORDER_CENTER_BONUS[to_square])
    return score
'''
if s.count(old)!=1:
    raise SystemExit(f'tactical order anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
