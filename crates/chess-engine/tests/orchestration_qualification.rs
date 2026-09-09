use chess_core::{Position, Square};
use chess_engine::{Engine, SearchLimits, StopToken};

#[test]
fn actual_move_history_reaches_threefold_at_the_third_occurrence() {
    let root = Position::from_fen("7k/8/8/8/8/8/K5Q1/8 w - - 0 1").expect("valid root FEN");
    let root_key = root.repetition_key().raw();
    let mut engine = Engine::new();
    engine.set_position(root.clone());

    play_cycle(&mut engine);
    assert_eq!(engine.position().repetition_key().raw(), root_key);
    assert_eq!(
        engine
            .repetition_history()
            .iter()
            .filter(|&&key| key == root_key)
            .count(),
        2,
        "one completed cycle is only the second occurrence"
    );
    let second_occurrence = engine.search_depth(2);
    assert!(
        second_occurrence.score > 0,
        "queen-up second occurrence must remain a live winning position"
    );
    assert_eq!(engine.position(), &root);

    play_cycle(&mut engine);
    assert_eq!(engine.position().repetition_key().raw(), root_key);
    assert_eq!(
        engine
            .repetition_history()
            .iter()
            .filter(|&&key| key == root_key)
            .count(),
        3
    );
    let history = engine.repetition_history().to_vec();
    let third_occurrence = engine.search_depth(3);
    assert_eq!(third_occurrence.score, 0, "third occurrence must be a draw");
    assert!(third_occurrence.best_move.is_some());
    assert_eq!(engine.position(), &root);
    assert_eq!(engine.repetition_history(), history);
}

#[test]
fn hash_resize_preserves_position_and_complete_game_history() {
    let mut engine = Engine::new();
    play_by_coordinates(&mut engine, "e2", "e4");
    play_by_coordinates(&mut engine, "e7", "e5");
    play_by_coordinates(&mut engine, "g1", "f3");

    let position = engine.position().clone();
    let history = engine.repetition_history().to_vec();
    assert!(history.len() > 1);

    assert_eq!(engine.set_hash_mb(64), 64);
    assert_eq!(engine.hash_mb(), 64);
    assert_eq!(engine.position(), &position);
    assert_eq!(engine.repetition_history(), history);

    let result = engine.search_depth(2);
    assert!(result.best_move.is_some());
    assert_eq!(engine.position(), &position);
    assert_eq!(engine.repetition_history(), history);
}

#[test]
fn stopped_search_then_reset_token_is_safe_on_the_same_engine() {
    let mut engine = Engine::new();
    let root = Position::from_fen("7k/8/8/8/8/8/K5Q1/8 w - - 0 1").expect("valid root FEN");
    engine.set_position(root.clone());
    let history = engine.repetition_history().to_vec();

    let stop = StopToken::new();
    stop.stop();
    let stopped = engine.search_with_limits(SearchLimits::depth(8), &stop);
    assert!(stopped.stopped);
    assert_eq!(stopped.result.depth, 0);
    assert_eq!(engine.position(), &root);
    assert_eq!(engine.repetition_history(), history);

    stop.reset();
    let completed = engine.search_with_limits(SearchLimits::depth(2), &stop);
    assert!(!completed.stopped);
    assert_eq!(completed.result.depth, 2);
    assert!(completed.result.score > 0);
    assert!(
        completed
            .result
            .best_move
            .is_some_and(|mv| root.legal_moves().as_slice().contains(&mv))
    );
    assert_eq!(engine.position(), &root);
    assert_eq!(engine.repetition_history(), history);
}

#[test]
fn node_limited_search_preserves_nontrivial_game_history_for_many_budgets() {
    const BUDGETS: [u64; 8] = [1, 2, 3, 5, 8, 13, 21, 34];

    let mut seed_engine = Engine::new();
    play_by_coordinates(&mut seed_engine, "e2", "e4");
    play_by_coordinates(&mut seed_engine, "e7", "e5");
    play_by_coordinates(&mut seed_engine, "g1", "f3");
    play_by_coordinates(&mut seed_engine, "b8", "c6");
    let position = seed_engine.position().clone();
    let history = seed_engine.repetition_history().to_vec();

    for budget in BUDGETS {
        let mut engine = Engine::new();
        engine.set_position_with_prior_history(
            position.clone(),
            history[..history.len() - 1].to_vec(),
        );
        let before_position = engine.position().clone();
        let before_history = engine.repetition_history().to_vec();

        let outcome = engine.search_with_limits(SearchLimits::nodes(8, budget), &StopToken::new());
        assert!(outcome.stopped, "small node budget should interrupt search");
        assert_eq!(engine.position(), &before_position, "budget {budget}");
        assert_eq!(
            engine.repetition_history(),
            before_history,
            "budget {budget}"
        );
    }
}

fn play_cycle(engine: &mut Engine) {
    play_by_coordinates(engine, "a2", "a3");
    play_by_coordinates(engine, "h8", "h7");
    play_by_coordinates(engine, "a3", "a2");
    play_by_coordinates(engine, "h7", "h8");
}

fn play_by_coordinates(engine: &mut Engine, from: &str, to: &str) {
    let from = square(from);
    let to = square(to);
    let mv = engine
        .position()
        .legal_moves()
        .iter()
        .copied()
        .find(|mv| mv.from() == from && mv.to() == to)
        .unwrap_or_else(|| panic!("expected legal move {from:?}->{to:?}"));
    assert!(engine.apply_move(mv));
}

fn square(name: &str) -> Square {
    let bytes = name.as_bytes();
    assert_eq!(bytes.len(), 2);
    let file = bytes[0].checked_sub(b'a').expect("file must be a-h");
    let rank = bytes[1].checked_sub(b'1').expect("rank must be 1-8");
    Square::from_file_rank(file, rank).expect("valid algebraic square")
}
