#!/usr/bin/env python3
"""Avoid full qsearch move generation on exits that need only legal-move existence."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-search/src/quiescence.rs")
text = path.read_text()

old = '''        let in_check = position.is_in_check(position.side_to_move());
        let moves = if in_check {
            generate_legal_moves_mut(position)
        } else {
            generate_legal_tactical_moves_mut(position)
        };

        if in_check && moves.is_empty() {
            return Some(terminal_score(position, ply));
        }

        if !in_check && moves.is_empty() {
            // A tactical-only empty list normally means a stable quiet position, but stalemate must
            // still score zero. Only this terminal-candidate path pays for full legal generation.
            if generate_legal_moves_mut(position).is_empty() {
                return Some(terminal_score(position, ply));
            }
            return Some(evaluate(position));
        }

        // Legal terminal detection happened above. The qsearch budget is local to this nominal leaf,
        // so a deep main search still receives the same tactical stabilization as a shallow search.
        if qply >= MAX_QSEARCH_PLY {
            return Some(evaluate(position));
        }

        let mut best = if in_check {
            -INFINITY
        } else {
            evaluate(position)
        };

        if !in_check {
            if best >= beta {
                return Some(best);
            }
            alpha = alpha.max(best);
        }
'''
new = '''        let in_check = position.is_in_check(position.side_to_move());

        // The local qsearch ceiling does not search a move. Preserve mate/stalemate precedence with
        // the accepted early-exit legal-existence probe instead of constructing and legality-filtering
        // a complete move list that would immediately be discarded.
        if qply >= MAX_QSEARCH_PLY {
            if !has_legal_move_mut(position) {
                return Some(terminal_score(position, ply));
            }
            return Some(evaluate(position));
        }

        // Outside check, stand pat is known before tactical generation. If it already fails high,
        // only terminal-vs-nonterminal status matters. Prove that with the same early legal probe
        // used by accepted RFP and avoid building/filtering the tactical list on the cutoff path.
        let stand_pat = if in_check {
            None
        } else {
            Some(evaluate(position))
        };
        if let Some(stand_pat) = stand_pat
            && stand_pat >= beta
        {
            if !has_legal_move_mut(position) {
                return Some(terminal_score(position, ply));
            }
            return Some(stand_pat);
        }

        let moves = if in_check {
            generate_legal_moves_mut(position)
        } else {
            generate_legal_tactical_moves_mut(position)
        };

        if in_check && moves.is_empty() {
            return Some(terminal_score(position, ply));
        }

        if !in_check && moves.is_empty() {
            // A tactical-only empty list normally means a stable quiet position, but stalemate must
            // still score zero. Only this terminal-candidate path pays for full legal generation.
            if generate_legal_moves_mut(position).is_empty() {
                return Some(terminal_score(position, ply));
            }
            return Some(stand_pat.expect("non-check qsearch has stand pat"));
        }

        let mut best = stand_pat.unwrap_or(-INFINITY);
        if let Some(stand_pat) = stand_pat {
            alpha = alpha.max(stand_pat);
        }
'''
text = replace_once(text, old, new, "qsearch early exits")

text = replace_once(
    text,
    '''    #[test]
    fn quiet_stable_leaf_does_not_need_tactical_moves() {''',
    '''    #[test]
    fn stand_pat_cutoff_preserves_stalemate_and_restores_position() {
        let mut live = Position::startpos();
        let live_root = live.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let live_score = searcher
            .quiescence(&mut live, &[], -INFINITY, -1, 0, 0, &NeverStop)
            .expect("stand-pat cutoff completes");
        assert_eq!(live_score, evaluate(&live));
        assert_eq!(live, live_root);

        let mut stalemate = Position::from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
            .expect("valid stalemate");
        let stalemate_root = stalemate.clone();
        let stale_score = searcher
            .quiescence(&mut stalemate, &[], -INFINITY, -1, 0, 0, &NeverStop)
            .expect("stalemate probe completes");
        assert_eq!(stale_score, 0);
        assert_eq!(stalemate, stalemate_root);
    }

    #[test]
    fn quiet_stable_leaf_does_not_need_tactical_moves() {''',
    "stand-pat terminal regression",
)

path.write_text(text)
