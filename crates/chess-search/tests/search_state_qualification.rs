use chess_core::Position;
use chess_search::{MATE_SCORE, SearchControl, Searcher};

struct StopAtNodes(u64);

impl SearchControl for StopAtNodes {
    fn should_stop(&self, nodes: u64) -> bool {
        nodes >= self.0
    }
}

const INTERRUPTION_ROOTS: [&str; 5] = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "4r2k/8/8/8/8/8/6Q1/4K3 w - - 0 1",
    "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
    "7k/P7/8/8/8/8/8/K7 w - - 0 1",
];

#[test]
fn interruption_restores_roots_across_many_recursive_cut_points() {
    const BUDGETS: [u64; 9] = [1, 2, 3, 5, 8, 13, 21, 34, 55];

    for fen in INTERRUPTION_ROOTS {
        for budget in BUDGETS {
            let mut position = Position::from_fen(fen).expect("qualification FEN must parse");
            let original = position.clone();
            let mut searcher = Searcher::with_tt_entries(1 << 12);
            let outcome = searcher.iterative_deepening_controlled(
                &mut position,
                8,
                &StopAtNodes(budget),
            );

            assert_eq!(
                position, original,
                "search leaked board state for budget {budget}: {fen}"
            );
            assert_eq!(
                position.zobrist_key(),
                position.recomputed_zobrist_key(),
                "search leaked incremental identity for budget {budget}: {fen}"
            );
            if budget == 1 {
                assert!(outcome.stopped, "budget one must stop before root search");
            }
        }
    }
}

#[test]
fn interrupted_searcher_can_be_reused_without_transient_state_leakage() {
    let mut interrupted_root = Position::from_fen(
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    )
    .expect("valid interruption root");
    let interrupted_original = interrupted_root.clone();

    let mut reused = Searcher::with_tt_entries(1 << 15);
    let stopped = reused.iterative_deepening_controlled(
        &mut interrupted_root,
        8,
        &StopAtNodes(37),
    );
    assert!(stopped.stopped);
    assert_eq!(interrupted_root, interrupted_original);

    let target = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1")
        .expect("valid target root");
    let mut reused_target = target.clone();
    let mut fresh_target = target.clone();
    let reused_result = reused.search_depth(&mut reused_target, 3);
    let fresh_result = Searcher::with_tt_entries(1 << 15).search_depth(&mut fresh_target, 3);

    assert_eq!(reused_result.score, fresh_result.score);
    assert_eq!(reused_result.best_move, fresh_result.best_move);
    assert_eq!(reused_target, target);
    assert_eq!(fresh_target, target);
}

#[test]
fn transposition_cache_cannot_override_halfmove_draw_context() {
    let live = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid live FEN");
    let drawn =
        Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 100 1").expect("valid draw FEN");

    assert_eq!(
        live.zobrist_key(),
        drawn.zobrist_key(),
        "TT identity deliberately excludes the halfmove clock"
    );

    let mut searcher = Searcher::with_tt_entries(1 << 12);
    let mut live_working = live.clone();
    let warm = searcher.search_depth(&mut live_working, 2);
    assert!(warm.score > 0, "queen-up control must not be scored as a draw");
    assert_eq!(live_working, live);

    let mut drawn_working = drawn.clone();
    let draw = searcher.search_depth(&mut drawn_working, 2);
    assert_eq!(draw.score, 0, "50-move context must beat a warm exact TT hit");
    assert!(draw.best_move.is_some(), "claimable draw position is not terminal");
    assert_eq!(drawn_working, drawn);

    let mut live_again = live.clone();
    let replay = searcher.search_depth(&mut live_again, 2);
    assert_eq!(replay.score, warm.score);
    assert_eq!(replay.best_move, warm.best_move);
    assert_eq!(live_again, live);
}

#[test]
fn repetition_threshold_and_normalized_identity_survive_tt_reuse() {
    let without_ep =
        Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid FEN");
    let with_irrelevant_ep =
        Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - e6 0 1").expect("valid FEN");

    assert_ne!(without_ep.zobrist_key(), with_irrelevant_ep.zobrist_key());
    assert_eq!(
        without_ep.repetition_key(),
        with_irrelevant_ep.repetition_key(),
        "irrelevant en-passant metadata must not split repetition identity"
    );

    let key = without_ep.repetition_key().raw();
    let mut searcher = Searcher::with_tt_entries(1 << 12);

    let mut warm_root = without_ep.clone();
    let warm = searcher.search_depth(&mut warm_root, 2);
    assert!(warm.score > 0);

    let mut second_occurrence = with_irrelevant_ep.clone();
    let second = searcher.search_depth_with_history(&mut second_occurrence, &[key], 2);
    assert!(
        second.score > 0,
        "one prior occurrence makes the root the second occurrence, not a draw"
    );
    assert_eq!(second_occurrence, with_irrelevant_ep);

    let mut third_occurrence = with_irrelevant_ep.clone();
    let third = searcher.search_depth_with_history(&mut third_occurrence, &[key, key], 2);
    assert_eq!(third.score, 0, "two prior occurrences make the root threefold");
    assert!(third.best_move.is_some());
    assert_eq!(third_occurrence, with_irrelevant_ep);
}

#[test]
fn mate_on_the_hundredth_halfmove_takes_precedence_over_draw_claim() {
    let mut root = Position::from_fen("7k/5Q2/6K1/8/8/8/8/8 w - - 99 1")
        .expect("valid mate-in-one FEN");
    let original = root.clone();
    let mut searcher = Searcher::with_tt_entries(1 << 12);
    let result = searcher.search_depth(&mut root, 1);

    assert!(
        result.score >= MATE_SCORE - 1,
        "checkmate must take precedence when a quiet mating move reaches halfmove 100"
    );
    let mating_move = result.best_move.expect("mate in one has a best move");
    let mut child = original.clone();
    let _undo = child.make_move(mating_move);
    assert_eq!(child.halfmove_clock(), 100);
    assert!(child.is_in_check(child.side_to_move()));
    assert!(child.legal_moves().is_empty());
    assert_eq!(root, original);
}
