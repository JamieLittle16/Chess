#!/usr/bin/env python3
"""Materialise the V15 Viridithas-v16 perseverance evaluator over exact V14 search."""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


eval_path = Path("crates/chess-eval/src/lib.rs")
eval_text = eval_path.read_text()
eval_text = replace_once(
    eval_text,
    "pub mod gestalt;\npub mod nnue;",
    "pub mod gestalt;\npub mod perseverance;\npub mod nnue;",
    "export perseverance module",
)
eval_path.write_text(eval_text)

path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

text = replace_once(
    text,
    """use chess_eval::{
    evaluate,
    gestalt::{
        AccumulatorState as GestaltAccumulatorState, Network as GestaltNetwork,
        PreparedAccumulatorUpdate as GestaltPreparedUpdate,
    },
};
""",
    """use chess_eval::{
    evaluate,
    gestalt::{
        AccumulatorState as GestaltAccumulatorState, Network as GestaltNetwork,
        PreparedAccumulatorUpdate as GestaltPreparedUpdate,
    },
    perseverance::{
        AccumulatorState as PerseveranceAccumulatorState, Network as PerseveranceNetwork,
        PreparedAccumulatorUpdate as PerseverancePreparedUpdate,
    },
};
""",
    "search evaluator imports",
)

needle = """impl GestaltSearchEvaluator {
    fn from_environment() -> Option<Self> {
        let path = std::env::var_os(\"CHESS_GESTALT_NETWORK\")?;
        let network = GestaltNetwork::from_file(std::path::Path::new(&path))
            .unwrap_or_else(|error| panic!(\"failed to load CHESS_GESTALT_NETWORK: {error}\"));
        Some(Self {
            network,
            accumulator: None,
        })
    }
}
"""
replacement = needle + """

struct PerseveranceSearchEvaluator {
    network: PerseveranceNetwork,
    accumulator: Option<PerseveranceAccumulatorState>,
}

impl PerseveranceSearchEvaluator {
    fn from_environment() -> Option<Self> {
        let path = std::env::var_os(\"CHESS_PERSEVERANCE_NETWORK\")?;
        let network = PerseveranceNetwork::from_file(std::path::Path::new(&path))
            .unwrap_or_else(|error| panic!(\"failed to load CHESS_PERSEVERANCE_NETWORK: {error}\"));
        Some(Self {
            network,
            accumulator: None,
        })
    }
}

#[derive(Clone, Copy)]
enum PreparedLeafUpdate {
    Gestalt(GestaltPreparedUpdate),
    Perseverance(PerseverancePreparedUpdate),
}
"""
text = replace_once(text, needle, replacement, "perseverance search evaluator")

text = replace_once(
    text,
    """    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],
    gestalt: Option<GestaltSearchEvaluator>,
}""",
    """    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],
    gestalt: Option<GestaltSearchEvaluator>,
    perseverance: Option<PerseveranceSearchEvaluator>,
}""",
    "searcher evaluator fields",
)

text = replace_once(
    text,
    """            move_contexts: [None; MAX_SEARCH_PLY],
            gestalt: GestaltSearchEvaluator::from_environment(),
        }""",
    """            move_contexts: [None; MAX_SEARCH_PLY],
            gestalt: GestaltSearchEvaluator::from_environment(),
            perseverance: PerseveranceSearchEvaluator::from_environment(),
        }""",
    "searcher evaluator init",
)

text = replace_once(
    text,
    """    fn reset_leaf_evaluator(&mut self, position: &Position) {
        if let Some(gestalt) = &mut self.gestalt {
            gestalt.accumulator = Some(
                GestaltAccumulatorState::from_position(&gestalt.network, position)
                    .expect(\"legal search root has both kings\"),
            );
        }
    }
""",
    """    fn reset_leaf_evaluator(&mut self, position: &Position) {
        if let Some(gestalt) = &mut self.gestalt {
            gestalt.accumulator = Some(
                GestaltAccumulatorState::from_position(&gestalt.network, position)
                    .expect(\"legal search root has both kings\"),
            );
        }
        if let Some(perseverance) = &mut self.perseverance {
            perseverance.accumulator = Some(
                PerseveranceAccumulatorState::from_position(&perseverance.network, position)
                    .expect(\"legal search root has both kings\"),
            );
        }
    }
""",
    "reset perseverance evaluator",
)

text = replace_once(
    text,
    """    fn leaf_evaluate(&self, position: &Position) -> i32 {
        if let Some(gestalt) = &self.gestalt
            && let Some(accumulator) = &gestalt.accumulator
        {
            return accumulator.evaluate(&gestalt.network, position.side_to_move());
        }
        evaluate(position)
    }
""",
    """    fn leaf_evaluate(&self, position: &Position) -> i32 {
        if let Some(perseverance) = &self.perseverance
            && let Some(accumulator) = &perseverance.accumulator
        {
            return accumulator.evaluate(&perseverance.network, position);
        }
        if let Some(gestalt) = &self.gestalt
            && let Some(accumulator) = &gestalt.accumulator
        {
            return accumulator.evaluate(&gestalt.network, position.side_to_move());
        }
        evaluate(position)
    }
""",
    "prefer perseverance leaf evaluation",
)

text = replace_once(
    text,
    """    fn prepare_leaf_move(
        &self,
        position: &Position,
        mv: ChessMove,
    ) -> Option<GestaltPreparedUpdate> {
        self.gestalt.as_ref().map(|_| {
            GestaltAccumulatorState::prepare_move(position, mv)
                .expect(\"generated legal move has a valid gestalt update\")
        })
    }
""",
    """    fn prepare_leaf_move(
        &self,
        position: &Position,
        mv: ChessMove,
    ) -> Option<PreparedLeafUpdate> {
        if self.perseverance.is_some() {
            return Some(PreparedLeafUpdate::Perseverance(
                PerseveranceAccumulatorState::prepare_move(position, mv)
                    .expect(\"generated legal move has a valid perseverance update\"),
            ));
        }
        self.gestalt.as_ref().map(|_| {
            PreparedLeafUpdate::Gestalt(
                GestaltAccumulatorState::prepare_move(position, mv)
                    .expect(\"generated legal move has a valid gestalt update\"),
            )
        })
    }
""",
    "prepare learned leaf update",
)

text = replace_once(
    text,
    """    fn apply_leaf_move(&mut self, position: &Position, prepared: Option<GestaltPreparedUpdate>) {
        if let Some(prepared) = prepared
            && let Some(gestalt) = &mut self.gestalt
        {
            gestalt
                .accumulator
                .as_mut()
                .expect(\"gestalt root state was initialised\")
                .apply_prepared(&gestalt.network, position, prepared)
                .expect(\"legal child position has valid gestalt state\");
        }
    }
""",
    """    fn apply_leaf_move(&mut self, position: &Position, prepared: Option<PreparedLeafUpdate>) {
        match prepared {
            Some(PreparedLeafUpdate::Gestalt(prepared)) => {
                let gestalt = self.gestalt.as_mut().expect(\"gestalt evaluator is active\");
                gestalt
                    .accumulator
                    .as_mut()
                    .expect(\"gestalt root state was initialised\")
                    .apply_prepared(&gestalt.network, position, prepared)
                    .expect(\"legal child position has valid gestalt state\");
            }
            Some(PreparedLeafUpdate::Perseverance(prepared)) => {
                let perseverance = self
                    .perseverance
                    .as_mut()
                    .expect(\"perseverance evaluator is active\");
                perseverance
                    .accumulator
                    .as_mut()
                    .expect(\"perseverance root state was initialised\")
                    .apply_prepared(&perseverance.network, position, prepared)
                    .expect(\"legal child position has valid perseverance state\");
            }
            None => {}
        }
    }
""",
    "apply learned leaf update",
)

text = replace_once(
    text,
    """    fn restore_leaf_move(&mut self, position: &Position, prepared: Option<GestaltPreparedUpdate>) {
        if let Some(prepared) = prepared
            && let Some(gestalt) = &mut self.gestalt
        {
            gestalt
                .accumulator
                .as_mut()
                .expect(\"gestalt root state was initialised\")
                .restore_after_unmake(&gestalt.network, position, prepared)
                .expect(\"restored legal position has valid gestalt state\");
        }
    }
""",
    """    fn restore_leaf_move(&mut self, position: &Position, prepared: Option<PreparedLeafUpdate>) {
        match prepared {
            Some(PreparedLeafUpdate::Gestalt(prepared)) => {
                let gestalt = self.gestalt.as_mut().expect(\"gestalt evaluator is active\");
                gestalt
                    .accumulator
                    .as_mut()
                    .expect(\"gestalt root state was initialised\")
                    .restore_after_unmake(&gestalt.network, position, prepared)
                    .expect(\"restored legal position has valid gestalt state\");
            }
            Some(PreparedLeafUpdate::Perseverance(prepared)) => {
                let perseverance = self
                    .perseverance
                    .as_mut()
                    .expect(\"perseverance evaluator is active\");
                perseverance
                    .accumulator
                    .as_mut()
                    .expect(\"perseverance root state was initialised\")
                    .restore_after_unmake(&perseverance.network, position, prepared)
                    .expect(\"restored legal position has valid perseverance state\");
            }
            None => {}
        }
    }
""",
    "restore learned leaf update",
)

path.write_text(text)
print("applied V15 perseverance evaluator integration")
