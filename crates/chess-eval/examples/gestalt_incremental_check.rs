//! Differential checker for the real pinned `gestalt` network.

use std::{env, path::PathBuf};

use chess_core::Position;
use chess_eval::gestalt::{AccumulatorState, Network};

fn main() -> Result<(), String> {
    let path = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or_else(|| "usage: gestalt_incremental_check <gestalt-b840.nnue>".to_owned())?;
    let network = Network::from_file(&path)?;
    let root = Position::startpos();
    let mut position = root.clone();
    let mut state = AccumulatorState::from_position(&network, &position)
        .ok_or_else(|| "could not build root accumulator".to_owned())?;

    let start_score = network
        .evaluate_full(&position)
        .ok_or_else(|| "could not full-evaluate startpos".to_owned())?;
    if start_score != 92 || state.evaluate(&network, position.side_to_move()) != start_score {
        return Err(format!(
            "certified startpos mismatch: full={start_score}, incremental={}",
            state.evaluate(&network, position.side_to_move())
        ));
    }

    let root_state = state.clone();
    let mut history = Vec::new();
    for ply in 0..256_usize {
        let moves = position.legal_moves();
        if moves.is_empty() {
            break;
        }
        let mv = moves[(ply.wrapping_mul(37).wrapping_add(17)) % moves.len()];
        let prepared = AccumulatorState::prepare_move(&position, mv)
            .ok_or_else(|| format!("could not prepare move {mv:?} at ply {ply}"))?;
        let undo = position.make_move(mv);
        state
            .apply_prepared(&network, &position, prepared)
            .ok_or_else(|| format!("could not apply move {mv:?} at ply {ply}"))?;
        require_match(&network, &state, &position, ply + 1)?;
        history.push((mv, undo, prepared));
    }

    let reached = history.len();
    while let Some((mv, undo, prepared)) = history.pop() {
        position.unmake_move(mv, undo);
        state
            .restore_after_unmake(&network, &position, prepared)
            .ok_or_else(|| format!("could not restore move {mv:?}"))?;
        require_match(&network, &state, &position, history.len())?;
    }

    if position != root || state != root_state {
        return Err("root position/accumulator not restored exactly".to_owned());
    }
    println!("gestalt incremental differential: {reached} pushes + {reached} pops exact; startpos={start_score}");
    Ok(())
}

fn require_match(
    network: &Network,
    state: &AccumulatorState,
    position: &Position,
    ply: usize,
) -> Result<(), String> {
    let full = network
        .evaluate_full(position)
        .ok_or_else(|| format!("full rebuild failed at ply {ply}"))?;
    let incremental = state.evaluate(network, position.side_to_move());
    if incremental != full {
        return Err(format!(
            "incremental mismatch at ply {ply}: incremental={incremental}, full={full}"
        ));
    }
    Ok(())
}
