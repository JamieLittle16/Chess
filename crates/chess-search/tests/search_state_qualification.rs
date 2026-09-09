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
            let outcome =
                searcher.iterative_deepening_controlled(&mut position, 8, &StopAtNodes(budget));

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
    let mut interrupted_root =
        Position::from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
            .expect("valid interruption root");
    let interrupted_original = interrupted_root.clone();

    let mut reused = Searcher::with_tt_entries(1 << 15);
    let stopped = reused.iterative_deepening_controlled(&mut interrupted_root, 8, &StopAtNodes(37));
    assert!(stopped.stopped);
    assert_eq!(interrupted_root, interrupted_original);

    let target = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid target root");
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
fn interrupted_same_root_then_complete_matches_fresh_searcher() {
    const BUDGETS: [u64; 6] = [2, 5, 13, 29, 61, 127];
    let root =
        Position::from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
            .expect("valid reuse root");

    for budget in BUDGETS {
        let mut reused = Searcher::with_tt_entries(1 << 15);
        let mut interrupted = root.clone();
        let stopped =
            reused.iterative_deepening_controlled(&mut interrupted, 8, &StopAtNodes(budget));
        assert!(
            stopped.stopped,
            "budget {budget} should interrupt the search"
        );
        assert_eq!(interrupted, root, "budget {budget}");

        let mut reused_root = root.clone();
        let mut fresh_root = root.clone();
        let reused_result = reused.search_depth(&mut reused_root, 3);
        let fresh_result = Searcher::with_tt_entries(1 << 15).search_depth(&mut fresh_root, 3);

        assert_eq!(reused_result.score, fresh_result.score, "budget {budget}");
        assert_eq!(
            reused_result.best_move, fresh_result.best_move,
            "budget {budget}"
        );
        assert_eq!(reused_root, root, "budget {budget}");
        assert_eq!(fresh_root, root, "budget {budget}");
    }
}

#[test]
fn one_entry_tt_collisions_never_reuse_foreign_positions() {
    let positions = [
        "7k/8/8/8/8/8/6Q1/K7 w - - 0 1",
        "7k/8/8/8/8/8/6r1/K7 w - - 0 1",
        "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    ];

    let mut reused = Searcher::with_tt_entries(1);
    for fen in positions.into_iter().cycle().take(12) {
        let root = Position::from_fen(fen).expect("collision FEN must parse");
        let mut reused_root = root.clone();
        let mut fresh_root = root.clone();

        let reused_result = reused.search_depth(&mut reused_root, 3);
        let fresh_result = Searcher::with_tt_entries(1).search_depth(&mut fresh_root, 3);

        assert_eq!(
            reused_result.score, fresh_result.score,
            "score mismatch: {fen}"
        );
        assert_eq!(
            reused_result.best_move, fresh_result.best_move,
            "best-move mismatch: {fen}"
        );
        assert_eq!(reused_root, root);
        assert_eq!(fresh_root, root);
    }
}

#[test]
fn transposition_cache_cannot_override_halfmove_draw_context() {
    let live = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid live FEN");
    let drawn = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 100 1").expect("valid draw FEN");

    assert_eq!(
        live.zobrist_key(),
        drawn.zobrist_key(),
        "TT identity deliberately excludes the halfmove clock"
    );

    let mut searcher = Searcher::with_tt_entries(1 << 12);
    let mut live_working = live.clone();
    let warm = searcher.search_depth(&mut live_working, 2);
    assert!(
        warm.score > 0,
        "queen-up control must not be scored as a draw"
    );
    assert_eq!(live_working, live);

    let mut drawn_working = drawn.clone();
    let draw = searcher.search_depth(&mut drawn_working, 2);
    assert_eq!(
        draw.score, 0,
        "50-move context must beat a warm exact TT hit"
    );
    assert!(
        draw.best_move.is_some(),
        "claimable draw position is not terminal"
    );
    assert_eq!(drawn_working, drawn);

    let mut live_again = live.clone();
    let replay = searcher.search_depth(&mut live_again, 2);
    assert_eq!(replay.score, warm.score);
    assert_eq!(replay.best_move, warm.best_move);
    assert_eq!(live_again, live);
}

#[test]
fn draw_context_search_cannot_poison_a_later_live_search() {
    let live = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid live FEN");
    let drawn = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 100 1").expect("valid draw FEN");
    let mut reused = Searcher::with_tt_entries(1 << 12);

    let mut draw_root = drawn.clone();
    let draw = reused.search_depth(&mut draw_root, 3);
    assert_eq!(draw.score, 0);
    assert_eq!(draw_root, drawn);

    let mut reused_live = live.clone();
    let mut fresh_live = live.clone();
    let reused_result = reused.search_depth(&mut reused_live, 3);
    let fresh_result = Searcher::with_tt_entries(1 << 12).search_depth(&mut fresh_live, 3);

    assert_eq!(reused_result.score, fresh_result.score);
    assert_eq!(reused_result.best_move, fresh_result.best_move);
    assert!(reused_result.score > 0);
    assert_eq!(reused_live, live);
    assert_eq!(fresh_live, live);
}

#[test]
fn repetition_threshold_and_normalized_identity_survive_tt_reuse() {
    let without_ep = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid FEN");
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
    assert_eq!(
        third.score, 0,
        "two prior occurrences make the root threefold"
    );
    assert!(third.best_move.is_some());
    assert_eq!(third_occurrence, with_irrelevant_ep);
}

#[test]
fn repetition_draw_context_cannot_poison_a_later_live_search() {
    let root = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid FEN");
    let key = root.repetition_key().raw();
    let mut reused = Searcher::with_tt_entries(1 << 12);

    let mut drawn_root = root.clone();
    let draw = reused.search_depth_with_history(&mut drawn_root, &[key, key], 3);
    assert_eq!(draw.score, 0);
    assert_eq!(drawn_root, root);

    let mut reused_live = root.clone();
    let mut fresh_live = root.clone();
    let reused_result = reused.search_depth(&mut reused_live, 3);
    let fresh_result = Searcher::with_tt_entries(1 << 12).search_depth(&mut fresh_live, 3);

    assert_eq!(reused_result.score, fresh_result.score);
    assert_eq!(reused_result.best_move, fresh_result.best_move);
    assert!(reused_result.score > 0);
    assert_eq!(reused_live, root);
    assert_eq!(fresh_live, root);
}

#[test]
fn fullmove_clock_is_search_irrelevant() {
    let roots = [
        (
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 73",
        ),
        (
            "7k/8/8/8/8/8/6Q1/K7 w - - 0 1",
            "7k/8/8/8/8/8/6Q1/K7 w - - 0 99",
        ),
    ];

    for (early_fen, late_fen) in roots {
        let early = Position::from_fen(early_fen).expect("valid early FEN");
        let late = Position::from_fen(late_fen).expect("valid late FEN");
        assert_eq!(early.zobrist_key(), late.zobrist_key());
        assert_eq!(early.repetition_key(), late.repetition_key());

        for depth in 1..=3 {
            let mut early_working = early.clone();
            let mut late_working = late.clone();
            let early_result =
                Searcher::with_tt_entries(1 << 12).search_depth(&mut early_working, depth);
            let late_result =
                Searcher::with_tt_entries(1 << 12).search_depth(&mut late_working, depth);

            assert_eq!(early_result.score, late_result.score, "depth {depth}");
            assert_eq!(
                early_result.best_move, late_result.best_move,
                "depth {depth}"
            );
            assert_eq!(early_working, early);
            assert_eq!(late_working, late);
        }
    }
}

#[test]
fn irrelevant_en_passant_metadata_is_search_neutral() {
    let plain = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid FEN");
    let irrelevant_ep = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - e6 0 1").expect("valid FEN");

    assert_ne!(plain.zobrist_key(), irrelevant_ep.zobrist_key());
    assert_eq!(plain.repetition_key(), irrelevant_ep.repetition_key());
    let plain_moves = plain.legal_moves();
    let ep_moves = irrelevant_ep.legal_moves();
    assert_eq!(plain_moves.as_slice(), ep_moves.as_slice());

    for depth in 1..=3 {
        let mut plain_working = plain.clone();
        let mut ep_working = irrelevant_ep.clone();
        let plain_result =
            Searcher::with_tt_entries(1 << 12).search_depth(&mut plain_working, depth);
        let ep_result = Searcher::with_tt_entries(1 << 12).search_depth(&mut ep_working, depth);

        assert_eq!(plain_result.score, ep_result.score, "depth {depth}");
        assert_eq!(plain_result.best_move, ep_result.best_move, "depth {depth}");
        assert_eq!(plain_working, plain);
        assert_eq!(ep_working, irrelevant_ep);
    }
}

#[test]
fn mate_in_one_distance_is_stable_across_depths_and_tt_reuse() {
    let root = Position::from_fen("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1").expect("valid mate FEN");
    let legal = root.legal_moves();
    let mut reused = Searcher::with_tt_entries(1 << 12);

    for depth in 1..=5 {
        let mut working = root.clone();
        let result = reused.search_depth(&mut working, depth);
        assert_eq!(result.score, MATE_SCORE - 1, "depth {depth}");
        let mv = result.best_move.expect("mate in one has a best move");
        assert!(legal.as_slice().contains(&mv));

        let mut child = root.clone();
        let _undo = child.make_move(mv);
        assert!(child.is_in_check(child.side_to_move()));
        assert!(child.legal_moves().is_empty());
        assert_eq!(working, root);
    }
}

#[test]
fn terminal_roots_are_depth_and_hash_invariant() {
    let checkmate = Position::from_fen("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1").expect("valid mate FEN");
    let stalemate =
        Position::from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1").expect("valid stalemate FEN");

    for entries in [0, 1, 17, 1 << 12] {
        let mut searcher = Searcher::with_tt_entries(entries);
        for depth in 0..=4 {
            let mut mate_working = checkmate.clone();
            let mate = searcher.search_depth(&mut mate_working, depth);
            assert_eq!(mate.best_move, None);
            assert_eq!(mate.score, -MATE_SCORE);
            assert_eq!(mate_working, checkmate);

            let mut stale_working = stalemate.clone();
            let stale = searcher.search_depth(&mut stale_working, depth);
            assert_eq!(stale.best_move, None);
            assert_eq!(stale.score, 0);
            assert_eq!(stale_working, stalemate);
        }
    }
}

#[test]
fn mate_on_the_hundredth_halfmove_takes_precedence_over_draw_claim() {
    let mut root =
        Position::from_fen("7k/5Q2/6K1/8/8/8/8/8 w - - 99 1").expect("valid mate-in-one FEN");
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
