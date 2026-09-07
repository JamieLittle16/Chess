use chess_core::{ChessMove, Color, MoveKind, PieceKind, Position};

const HISTORY_MAX: i32 = 8_192;
const HISTORY_MIN: i32 = -HISTORY_MAX;

/// Fixed-size search-local ordering history.
///
/// The tables live inside `Searcher` and allocate no heap memory. Quiet history is keyed by
/// side/from/to. Capture history is keyed by side/attacker/to/victim. Updates use a gravity formula
/// so long searches cannot permanently saturate one entry.
#[derive(Clone)]
pub(super) struct HistoryTables {
    quiet: [[[i16; 64]; 64]; 2],
    capture: [[[[i16; 6]; 64]; 6]; 2],
}

impl Default for HistoryTables {
    fn default() -> Self {
        Self {
            quiet: [[[0; 64]; 64]; 2],
            capture: [[[[0; 6]; 64]; 6]; 2],
        }
    }
}

impl HistoryTables {
    #[inline]
    pub(super) fn quiet_score(&self, color: Color, mv: ChessMove) -> i32 {
        i32::from(
            self.quiet[color.index()][usize::from(mv.from().index())]
                [usize::from(mv.to().index())],
        )
    }

    pub(super) fn reward_quiet(&mut self, color: Color, mv: ChessMove, depth: u8) {
        let bonus = history_bonus(depth);
        let entry = &mut self.quiet[color.index()][usize::from(mv.from().index())]
            [usize::from(mv.to().index())];
        update(entry, bonus);
    }

    pub(super) fn penalize_quiet(&mut self, color: Color, mv: ChessMove, depth: u8) {
        let malus = -(history_bonus(depth) / 2).max(16);
        let entry = &mut self.quiet[color.index()][usize::from(mv.from().index())]
            [usize::from(mv.to().index())];
        update(entry, malus);
    }

    #[inline]
    pub(super) fn capture_score(&self, position: &Position, mv: ChessMove) -> i32 {
        let Some((color, attacker, victim)) = capture_key(position, mv) else {
            return 0;
        };
        i32::from(
            self.capture[color.index()][attacker.index()][usize::from(mv.to().index())]
                [victim.index()],
        )
    }

    pub(super) fn reward_capture(&mut self, position: &Position, mv: ChessMove, depth: u8) {
        let Some((color, attacker, victim)) = capture_key(position, mv) else {
            return;
        };
        let bonus = history_bonus(depth);
        let entry = &mut self.capture[color.index()][attacker.index()]
            [usize::from(mv.to().index())][victim.index()];
        update(entry, bonus);
    }

    pub(super) fn penalize_capture(&mut self, position: &Position, mv: ChessMove, depth: u8) {
        let Some((color, attacker, victim)) = capture_key(position, mv) else {
            return;
        };
        let malus = -(history_bonus(depth) / 3).max(12);
        let entry = &mut self.capture[color.index()][attacker.index()]
            [usize::from(mv.to().index())][victim.index()];
        update(entry, malus);
    }
}

#[inline]
fn history_bonus(depth: u8) -> i32 {
    let depth = i32::from(depth);
    (32 * depth * depth).clamp(32, 2_048)
}

#[inline]
fn update(entry: &mut i16, bonus: i32) {
    let bonus = bonus.clamp(HISTORY_MIN, HISTORY_MAX);
    let current = i32::from(*entry);
    let next = current + bonus - current * bonus.abs() / HISTORY_MAX;
    *entry = next.clamp(HISTORY_MIN, HISTORY_MAX) as i16;
}

fn capture_key(position: &Position, mv: ChessMove) -> Option<(Color, PieceKind, PieceKind)> {
    if !mv.kind().is_capture() {
        return None;
    }
    let moving = position.piece_at(mv.from())?;
    let victim = if mv.kind() == MoveKind::EnPassant {
        PieceKind::Pawn
    } else {
        position.piece_at(mv.to())?.kind()
    };
    Some((moving.color(), moving.kind(), victim))
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, Position, Square};

    use super::HistoryTables;

    #[test]
    fn quiet_reward_and_malus_are_bounded_and_directional() {
        let position = Position::startpos();
        let mv = position.legal_moves()[0];
        let mut history = HistoryTables::default();
        assert_eq!(history.quiet_score(Color::White, mv), 0);
        history.reward_quiet(Color::White, mv, 6);
        assert!(history.quiet_score(Color::White, mv) > 0);
        for _ in 0..256 {
            history.penalize_quiet(Color::White, mv, 12);
        }
        assert!((-8_192..=8_192).contains(&history.quiet_score(Color::White, mv)));
    }

    #[test]
    fn capture_history_is_keyed_by_attacker_target_and_victim() {
        let position = Position::from_fen("7k/8/8/8/3q4/8/3R4/K7 w - - 0 1").expect("valid FEN");
        let d2 = Square::from_file_rank(3, 1).expect("d2");
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let capture = position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.from() == d2 && mv.to() == d4)
            .expect("Rxd4 is legal");
        let mut history = HistoryTables::default();
        assert_eq!(history.capture_score(&position, capture), 0);
        history.reward_capture(&position, capture, 5);
        assert!(history.capture_score(&position, capture) > 0);
    }
}
