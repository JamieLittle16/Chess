//! Differential checker for the real pinned Hyperstition v92 network.

use std::{env, path::PathBuf};

use chess_core::{ChessMove, MoveKind, Position};
use chess_eval::hyperstition::{AccumulatorState, Network, PreparedAccumulatorUpdate};

fn main() -> Result<(), String> {
    let path = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or_else(|| "usage: hyperstition_incremental_check <hyperstition-b400.nnue>".to_owned())?;
    let network = Network::from_file(&path)?;

    certify_long_walk(&network)?;
    certify_special_move(
        &network,
        "castling",
        "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        |mv| mv.kind() == MoveKind::KingCastle,
    )?;
    certify_special_move(
        &network,
        "en-passant",
        "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        |mv| mv.kind() == MoveKind::EnPassant,
    )?;
    certify_special_move(
        &network,
        "promotion",
        "7k/P7/8/8/8/8/8/K7 w - - 0 1",
        |mv| mv.kind().is_promotion(),
    )?;
    certify_special_move(
        &network,
        "king-bucket-crossing",
        "7k/8/8/8/8/8/8/4K3 w - - 0 1",
        |mv| {
            mv.from().file() == 4
                && mv.from().rank() == 0
                && mv.to().file() == 3
                && mv.to().rank() == 0
        },
    )?;

    println!("hyperstition incremental certification: long walk + special moves exact");
    Ok(())
}

fn certify_long_walk(network: &Network) -> Result<(), String> {
    let root = Position::startpos();
    let mut position = root.clone();
    let mut state = AccumulatorState::from_position(network, &position)
        .ok_or_else(|| "could not build startpos accumulator".to_owned())?;
    require_match(network, &state, &position, "startpos")?;

    let root_state = state.clone();
    let mut history = Vec::new();
    for ply in 0..384_usize {
        let moves = position.legal_moves();
        if moves.is_empty() {
            break;
        }
        let mv = moves[(ply.wrapping_mul(37).wrapping_add(17)) % moves.len()];
        let prepared = AccumulatorState::prepare_move(&position, mv)
            .ok_or_else(|| format!("could not prepare move {mv:?} at ply {ply}"))?;
        let undo = position.make_move(mv);
        state
            .apply_prepared(network, &position, prepared)
            .ok_or_else(|| format!("could not apply move {mv:?} at ply {ply}"))?;
        require_match(network, &state, &position, &format!("walk ply {}", ply + 1))?;
        history.push((mv, undo, prepared));
    }

    let reached = history.len();
    while let Some((mv, undo, prepared)) = history.pop() {
        position.unmake_move(mv, undo);
        state
            .restore_after_unmake(network, &position, prepared)
            .ok_or_else(|| format!("could not restore move {mv:?}"))?;
        require_match(
            network,
            &state,
            &position,
            &format!("walk restore ply {}", history.len()),
        )?;
    }

    if position != root || state != root_state {
        return Err("long-walk root position/accumulator not restored exactly".to_owned());
    }
    println!("long walk: {reached} pushes + {reached} pops exact");
    Ok(())
}

fn certify_special_move(
    network: &Network,
    name: &str,
    fen: &str,
    predicate: impl Fn(ChessMove) -> bool,
) -> Result<(), String> {
    let root = Position::from_fen(fen).map_err(|error| format!("{name}: invalid FEN: {error}"))?;
    let mut position = root.clone();
    let mut state = AccumulatorState::from_position(network, &position)
        .ok_or_else(|| format!("{name}: could not build root accumulator"))?;
    let root_state = state.clone();
    require_match(network, &state, &position, &format!("{name} root"))?;

    let mv = position
        .legal_moves()
        .iter()
        .copied()
        .find(|&mv| predicate(mv))
        .ok_or_else(|| format!("{name}: expected move was not legal"))?;
    let prepared = AccumulatorState::prepare_move(&position, mv)
        .ok_or_else(|| format!("{name}: could not prepare {mv:?}"))?;
    let undo = position.make_move(mv);
    state
        .apply_prepared(network, &position, prepared)
        .ok_or_else(|| format!("{name}: could not apply {mv:?}"))?;
    require_match(network, &state, &position, &format!("{name} after"))?;

    position.unmake_move(mv, undo);
    state
        .restore_after_unmake(network, &position, prepared)
        .ok_or_else(|| format!("{name}: could not restore {mv:?}"))?;
    require_match(network, &state, &position, &format!("{name} restored"))?;
    if position != root || state != root_state {
        return Err(format!("{name}: root position/accumulator not restored exactly"));
    }
    println!("{name}: push + pop exact ({mv:?})");
    Ok(())
}

fn require_match(
    network: &Network,
    state: &AccumulatorState,
    position: &Position,
    label: &str,
) -> Result<(), String> {
    let full = network
        .evaluate_full(position)
        .ok_or_else(|| format!("{label}: full rebuild failed"))?;
    let incremental = state.evaluate(network, position);
    if incremental != full {
        return Err(format!(
            "{label}: incremental mismatch: incremental={incremental}, full={full}"
        ));
    }
    Ok(())
}

#[allow(dead_code)]
fn _assert_prepared_is_copy(_: PreparedAccumulatorUpdate) {}
