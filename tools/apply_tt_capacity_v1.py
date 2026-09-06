from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement target, found {count}")
    file.write_text(text.replace(old, new, 1))


# chess-search: keep the tiny deterministic default, add exact memory-sized construction.
search = "crates/chess-search/src/lib.rs"
replace_once(
    search,
    "pub const DEFAULT_TT_ENTRIES: usize = 1 << 15;\n\nconst INFINITY: i32 = 32_000;",
    "pub const DEFAULT_TT_ENTRIES: usize = 1 << 15;\nconst BYTES_PER_MEGABYTE: usize = 1024 * 1024;\n\nconst INFINITY: i32 = 32_000;",
)
replace_once(
    search,
    """    pub fn with_tt_entries(entries: usize) -> Self {\n        Self {\n            table: TranspositionTable::new(entries),\n            nodes: 0,\n            tt_hits: 0,\n            path_keys: [0; MAX_SEARCH_PLY],\n        }\n    }\n\n    /// Search one exact nominal depth while restoring `position` exactly.\n""",
    """    pub fn with_tt_entries(entries: usize) -> Self {\n        Self {\n            table: TranspositionTable::new(entries),\n            nodes: 0,\n            tt_hits: 0,\n            path_keys: [0; MAX_SEARCH_PLY],\n        }\n    }\n\n    /// Construct search state with a transposition table bounded by whole mebibytes.\n    ///\n    /// This is the production-facing sizing API. The deterministic reference default remains\n    /// entry-count based so benchmark identity does not depend on platform allocator details.\n    #[must_use]\n    pub fn with_tt_megabytes(megabytes: usize) -> Self {\n        Self::with_tt_entries(tt_entries_for_megabytes(megabytes))\n    }\n\n    #[must_use]\n    pub fn tt_capacity_entries(&self) -> usize {\n        self.table.len()\n    }\n\n    /// Search one exact nominal depth while restoring `position` exactly.\n""",
)
replace_once(
    search,
    """impl Default for Searcher {\n    fn default() -> Self {\n        Self::with_tt_entries(DEFAULT_TT_ENTRIES)\n    }\n}\n""",
    """/// Convert a whole-mebibyte TT budget into the maximum number of complete entries that fit.\n#[must_use]\npub fn tt_entries_for_megabytes(megabytes: usize) -> usize {\n    let bytes = megabytes.saturating_mul(BYTES_PER_MEGABYTE);\n    (bytes / core::mem::size_of::<TtEntry>()).max(1)\n}\n\nimpl Default for Searcher {\n    fn default() -> Self {\n        Self::with_tt_entries(DEFAULT_TT_ENTRIES)\n    }\n}\n""",
)
replace_once(
    search,
    """    fn new(entries: usize) -> Self {\n        Self {\n            entries: vec![TtEntry::EMPTY; entries],\n        }\n    }\n\n    fn probe(&self, key: u64) -> Option<TtEntry> {\n""",
    """    fn new(entries: usize) -> Self {\n        Self {\n            entries: vec![TtEntry::EMPTY; entries],\n        }\n    }\n\n    fn len(&self) -> usize {\n        self.entries.len()\n    }\n\n    fn probe(&self, key: u64) -> Option<TtEntry> {\n""",
)
replace_once(
    search,
    """    use super::{\n        MATE_SCORE, SearchControl, Searcher, has_two_prior_occurrences, iterative_deepening,\n        score_from_tt, score_to_tt, search, search_mut,\n    };\n\n    struct NodeStop(u64);\n""",
    """    use super::{\n        MATE_SCORE, SearchControl, Searcher, has_two_prior_occurrences, iterative_deepening,\n        score_from_tt, score_to_tt, search, search_mut, tt_entries_for_megabytes,\n    };\n\n    #[test]\n    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {\n        let expected = (1024 * 1024) / core::mem::size_of::<super::TtEntry>();\n        assert_eq!(tt_entries_for_megabytes(1), expected);\n        assert_eq!(\n            Searcher::with_tt_megabytes(1).tt_capacity_entries(),\n            expected\n        );\n        assert_eq!(tt_entries_for_megabytes(0), 1);\n    }\n\n    struct NodeStop(u64);\n""",
)

# chess-engine: use a serious memory-sized TT by default and preserve configuration across games.
engine = "crates/chess-engine/src/lib.rs"
replace_once(
    engine,
    "use chess_search::{SearchControl, Searcher};\n",
    """use chess_search::{SearchControl, Searcher};\n\n/// Default transposition-table memory for actual engine frontends.\npub const DEFAULT_HASH_MB: usize = 32;\n/// Smallest accepted production TT setting.\npub const MIN_HASH_MB: usize = 1;\n/// Defensive upper bound for protocol/front-end supplied TT memory.\npub const MAX_HASH_MB: usize = 1024;\n""",
)
replace_once(
    engine,
    """pub struct Engine {\n    position: Position,\n    repetition_history: Vec<u64>,\n    searcher: Searcher,\n}\n\nimpl Engine {\n    #[must_use]\n    pub fn new() -> Self {\n        let position = Position::startpos();\n        let repetition_history = vec![position.repetition_key().raw()];\n        Self {\n            position,\n            repetition_history,\n            searcher: Searcher::default(),\n        }\n    }\n\n    #[must_use]\n    pub const fn position(&self) -> &Position {\n""",
    """pub struct Engine {\n    position: Position,\n    repetition_history: Vec<u64>,\n    searcher: Searcher,\n    hash_mb: usize,\n}\n\nimpl Engine {\n    #[must_use]\n    pub fn new() -> Self {\n        Self::with_hash_mb(DEFAULT_HASH_MB)\n    }\n\n    #[must_use]\n    pub fn with_hash_mb(hash_mb: usize) -> Self {\n        let hash_mb = hash_mb.clamp(MIN_HASH_MB, MAX_HASH_MB);\n        let position = Position::startpos();\n        let repetition_history = vec![position.repetition_key().raw()];\n        Self {\n            position,\n            repetition_history,\n            searcher: Searcher::with_tt_megabytes(hash_mb),\n            hash_mb,\n        }\n    }\n\n    #[must_use]\n    pub const fn hash_mb(&self) -> usize {\n        self.hash_mb\n    }\n\n    /// Resize and clear search memory without touching the current game state.\n    pub fn set_hash_mb(&mut self, hash_mb: usize) -> usize {\n        let hash_mb = hash_mb.clamp(MIN_HASH_MB, MAX_HASH_MB);\n        self.searcher = Searcher::with_tt_megabytes(hash_mb);\n        self.hash_mb = hash_mb;\n        hash_mb\n    }\n\n    #[must_use]\n    pub const fn position(&self) -> &Position {\n""",
)
replace_once(
    engine,
    """    /// Start a fresh game and discard search memory from the previous game.\n    pub fn new_game(&mut self) {\n        *self = Self::new();\n    }\n""",
    """    /// Start a fresh game and discard search memory from the previous game.\n    ///\n    /// Frontend configuration, including the selected hash size, survives `ucinewgame`.\n    pub fn new_game(&mut self) {\n        let hash_mb = self.hash_mb;\n        *self = Self::with_hash_mb(hash_mb);\n    }\n""",
)
replace_once(
    engine,
    """    use super::{ClockState, Engine, SearchLimits, StopToken};\n\n    #[test]\n    fn illegal_external_move_is_rejected_without_mutation() {\n""",
    """    use super::{\n        ClockState, DEFAULT_HASH_MB, Engine, MAX_HASH_MB, MIN_HASH_MB, SearchLimits, StopToken,\n    };\n\n    #[test]\n    fn hash_configuration_is_bounded_and_survives_new_game() {\n        let mut engine = Engine::new();\n        assert_eq!(engine.hash_mb(), DEFAULT_HASH_MB);\n        assert_eq!(engine.set_hash_mb(64), 64);\n        assert_eq!(engine.hash_mb(), 64);\n\n        let root = engine.position().clone();\n        assert_eq!(engine.set_hash_mb(0), MIN_HASH_MB);\n        assert_eq!(engine.position(), &root);\n        assert_eq!(engine.set_hash_mb(usize::MAX), MAX_HASH_MB);\n\n        engine.set_hash_mb(64);\n        engine.new_game();\n        assert_eq!(engine.hash_mb(), 64);\n        assert_eq!(engine.position(), &Position::startpos());\n        assert_eq!(engine.repetition_history().len(), 1);\n    }\n\n    #[test]\n    fn illegal_external_move_is_rejected_without_mutation() {\n""",
)

# chess-uci: expose the production TT through the standard Hash option.
uci = "crates/chess-uci/src/lib.rs"
replace_once(
    uci,
    "use chess_engine::{ClockState, Engine, MATE_SCORE, SearchLimits, SearchResult, StopToken};\n",
    """use chess_engine::{\n    ClockState, DEFAULT_HASH_MB, Engine, MATE_SCORE, MAX_HASH_MB, MIN_HASH_MB, SearchLimits,\n    SearchResult, StopToken,\n};\n""",
)
replace_once(
    uci,
    """                vec![\n                    \"id name Chess 0.1.0\".to_owned(),\n                    \"id author Jamie Little\".to_owned(),\n                    \"uciok\".to_owned(),\n                ],\n""",
    """                vec![\n                    \"id name Chess 0.1.0\".to_owned(),\n                    \"id author Jamie Little\".to_owned(),\n                    format!(\n                        \"option name Hash type spin default {DEFAULT_HASH_MB} min {MIN_HASH_MB} max {MAX_HASH_MB}\"\n                    ),\n                    \"uciok\".to_owned(),\n                ],\n""",
)
replace_once(
    uci,
    """            \"isready\" => response(vec![\"readyok\".to_owned()], false),\n            \"ucinewgame\" => {\n""",
    """            \"isready\" => response(vec![\"readyok\".to_owned()], false),\n            \"setoption\" => self.handle_setoption(&tokens),\n            \"ucinewgame\" => {\n""",
)
replace_once(
    uci,
    """    fn handle_go(&mut self, tokens: &[&str]) -> UciResponse {\n""",
    """    fn handle_setoption(&mut self, tokens: &[&str]) -> UciResponse {\n        match parse_hash_option(tokens) {\n            Ok(hash_mb) => {\n                self.engine.set_hash_mb(hash_mb);\n                response(Vec::new(), false)\n            }\n            Err(message) => response(vec![format!(\"info string {message}\")], false),\n        }\n    }\n\n    fn handle_go(&mut self, tokens: &[&str]) -> UciResponse {\n""",
)
replace_once(
    uci,
    """#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]\nstruct GoRequest {\n""",
    """fn parse_hash_option(tokens: &[&str]) -> Result<usize, &'static str> {\n    if tokens.get(1) != Some(&\"name\")\n        || tokens.get(2) != Some(&\"Hash\")\n        || tokens.get(3) != Some(&\"value\")\n        || tokens.len() != 5\n    {\n        return Err(\"supported setoption syntax is: setoption name Hash value <MiB>\");\n    }\n\n    let value = tokens[4]\n        .parse::<usize>()\n        .map_err(|_| \"Hash requires an integer MiB value\")?;\n    if !(MIN_HASH_MB..=MAX_HASH_MB).contains(&value) {\n        return Err(\"Hash value is outside the advertised range\");\n    }\n    Ok(value)\n}\n\n#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]\nstruct GoRequest {\n""",
)
replace_once(
    uci,
    """    use chess_core::{Color, PieceKind, Position};\n\n    use super::{\n        DEFAULT_LIMIT_DEPTH, UciSession, format_uci_move, parse_go_request, resolve_uci_move,\n    };\n""",
    """    use chess_core::{Color, PieceKind, Position};\n    use chess_engine::{DEFAULT_HASH_MB, MAX_HASH_MB};\n\n    use super::{\n        DEFAULT_LIMIT_DEPTH, UciSession, format_uci_move, parse_go_request, resolve_uci_move,\n    };\n""",
)
replace_once(
    uci,
    """        assert_eq!(\n            uci.lines(),\n            [\"id name Chess 0.1.0\", \"id author Jamie Little\", \"uciok\"]\n        );\n        assert_eq!(session.handle_line(\"isready\").lines(), [\"readyok\"]);\n    }\n\n    #[test]\n    fn position_move_sequence_is_resolved_through_legal_chess_and_history() {\n""",
    """        assert_eq!(\n            uci.lines(),\n            [\n                \"id name Chess 0.1.0\",\n                \"id author Jamie Little\",\n                \"option name Hash type spin default 32 min 1 max 1024\",\n                \"uciok\",\n            ]\n        );\n        assert_eq!(session.handle_line(\"isready\").lines(), [\"readyok\"]);\n    }\n\n    #[test]\n    fn hash_option_resizes_search_memory_without_losing_configuration_on_new_game() {\n        let mut session = UciSession::new();\n        assert_eq!(session.engine().hash_mb(), DEFAULT_HASH_MB);\n        assert!(\n            session\n                .handle_line(\"setoption name Hash value 64\")\n                .lines()\n                .is_empty()\n        );\n        assert_eq!(session.engine().hash_mb(), 64);\n\n        let invalid = session.handle_line(\"setoption name Hash value 0\");\n        assert_eq!(invalid.lines().len(), 1);\n        assert_eq!(session.engine().hash_mb(), 64);\n\n        let too_large = format!(\"setoption name Hash value {}\", MAX_HASH_MB + 1);\n        assert_eq!(session.handle_line(&too_large).lines().len(), 1);\n        assert_eq!(session.engine().hash_mb(), 64);\n\n        session.handle_line(\"ucinewgame\");\n        assert_eq!(session.engine().hash_mb(), 64);\n    }\n\n    #[test]\n    fn position_move_sequence_is_resolved_through_legal_chess_and_history() {\n""",
)

# Documentation: make the reference/production split and remaining limitations explicit.
doc = "docs/UCI.md"
replace_once(
    doc,
    "Status: **M3 interruptible worker + standard clocks + draw history**",
    "Status: **M4 interruptible worker + clocks + draw history + configurable hash**",
)
replace_once(
    doc,
    """- `isready`\n- `ucinewgame`\n""",
    """- `isready`\n- `setoption name Hash value <MiB>`\n- `ucinewgame`\n""",
)
replace_once(
    doc,
    """Move text uses standard UCI long algebraic coordinate form such as `e2e4`, `e7e8q` and `e1g1`.\n\nA search emits""",
    """Move text uses standard UCI long algebraic coordinate form such as `e2e4`, `e7e8q` and `e1g1`.\n\n`Hash` is the first configurable UCI engine option. The deterministic `Searcher::default()` remains the small 32,768-entry reference configuration used by behavioral CI, while `Engine::new()` uses a 32 MiB production TT. UCI accepts 1–1024 MiB. Resizing clears only search memory and never mutates board/history state; `ucinewgame` clears the table while preserving the selected hash size.\n\nA search emits""",
)
replace_once(
    doc,
    "- there are no configurable UCI options yet;",
    "- `Hash` is currently the only configurable engine option;",
)
replace_once(
    doc,
    """14. the threaded executable compiling under strict Clippy with the engine remaining single-owner;\n15. workspace formatting, debug tests, release tests and the pinned `reference-search-v2` signature remaining green.\n""",
    """14. `Hash` advertising, bounded resizing, state preservation and persistence across `ucinewgame`;\n15. the threaded executable compiling under strict Clippy with the engine remaining single-owner;\n16. workspace formatting, debug tests, release tests and the pinned current reference-search signature remaining green.\n""",
)
