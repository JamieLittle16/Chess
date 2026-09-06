use chess_core::{Position, Square};
use chess_search::Searcher;

fn child_repetition_key(position: &Position, mv: chess_core::ChessMove) -> u64 {
    let mut child = position.clone();
    let _undo = child.make_move(mv);
    child.repetition_key().raw()
}

#[test]
fn winning_side_avoids_available_threefold_when_positive_play_exists() {
    let mut root = Position::from_fen("7k/8/8/8/8/8/K7/1Q6 w - - 0 1").expect("valid FEN");
    let original = root.clone();
    let legal = root.legal_moves();
    assert!(legal.len() >= 2, "test position needs alternatives");

    // Pretend the first legal child has already occurred twice in the real game history. Reaching
    // it again is therefore an immediate threefold draw. Every other child remains a fresh
    // queen-up position.
    let drawing_move = legal.as_slice()[0];
    let drawing_key = child_repetition_key(&root, drawing_move);

    let mut searcher = Searcher::default();
    let result = searcher.search_depth_with_history(&mut root, &[drawing_key, drawing_key], 1);

    assert!(
        result.score > 0,
        "a winning side should prefer a positive continuation to a draw"
    );
    assert_ne!(
        result.best_move,
        Some(drawing_move),
        "a winning side must not voluntarily repeat when a positive alternative exists"
    );
    assert_eq!(root, original, "search must restore the root exactly");
}

#[test]
fn losing_side_seeks_available_threefold_over_negative_continuations() {
    let mut root = Position::from_fen("7k/8/8/8/8/8/K7/1Q6 b - - 0 1").expect("valid FEN");
    let original = root.clone();
    let legal = root.legal_moves();
    assert!(legal.len() >= 2, "test position needs alternatives");

    // Mark exactly one legal child as the third occurrence. Black is otherwise a queen down, so a
    // true draw (0) must dominate all ordinary negative continuations under negamax.
    let drawing_move = legal.as_slice()[0];
    let drawing_key = child_repetition_key(&root, drawing_move);

    let mut searcher = Searcher::default();
    let result = searcher.search_depth_with_history(&mut root, &[drawing_key, drawing_key], 1);

    assert_eq!(
        result.score, 0,
        "a forced/claimable draw is better than remaining losing"
    );
    assert_eq!(
        result.best_move,
        Some(drawing_move),
        "a losing side should choose the available repetition"
    );
    assert_eq!(root, original, "search must restore the root exactly");
}

#[test]
fn stalemate_is_an_exact_draw_not_a_static_evaluation() {
    let mut root = Position::from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1").expect("valid FEN");
    let mut searcher = Searcher::default();
    let result = searcher.search_depth(&mut root, 4);

    assert_eq!(result.best_move, None);
    assert_eq!(result.score, 0);
}

#[test]
fn winning_side_avoids_immediate_stalemate_when_positive_play_exists() {
    let mut root = Position::from_fen("k7/8/2K5/2Q5/8/8/8/8 w - - 0 1").expect("valid FEN");
    let original = root.clone();
    let c5 = Square::from_file_rank(2, 4).expect("c5");
    let b6 = Square::from_file_rank(1, 5).expect("b6");
    let stalemating_move = root
        .legal_moves()
        .as_slice()
        .iter()
        .copied()
        .find(|mv| mv.from() == c5 && mv.to() == b6)
        .expect("Qc5-b6 is legal");

    let mut stalemate = root.clone();
    let _undo = stalemate.make_move(stalemating_move);
    assert!(!stalemate.is_in_check(stalemate.side_to_move()));
    assert!(stalemate.legal_moves().is_empty(), "Qc5-b6 must stalemate");

    let mut searcher = Searcher::default();
    let result = searcher.search_depth(&mut root, 1);

    assert!(
        result.score > 0,
        "winning K+Q vs K should prefer continuing the win to stalemate"
    );
    assert_ne!(
        result.best_move,
        Some(stalemating_move),
        "a winning side must reject an immediate stalemate"
    );
    assert_eq!(root, original, "search must restore the root exactly");
}
