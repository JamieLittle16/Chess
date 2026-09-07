#!/usr/bin/env python3
"""Poll wall-clock deadlines periodically while preserving exact node/stop checks."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-engine/src/lib.rs")
text = path.read_text()

text = replace_once(
    text,
    "use std::{\n    sync::{",
    "use std::{\n    cell::Cell,\n    sync::{",
    "Cell import",
)

text = replace_once(
    text,
    "pub const MAX_HASH_MB: usize = 1024;",
    "pub const MAX_HASH_MB: usize = 1024;\n\n// Wall-clock queries are materially more expensive than the atomic stop/node checks. Timed search\n// therefore samples the deadline every small fixed block of visited nodes. Exact node limits and\n// external stop requests remain checked at every search-control boundary.\nconst DEADLINE_POLL_INTERVAL_NODES: u64 = 64;",
    "deadline poll constant",
)

text = replace_once(
    text,
    '''        let control = EngineControl {
            stop,
            max_nodes: limits.max_nodes,
            deadline,
        };''',
    '''        let control = EngineControl {
            stop,
            max_nodes: limits.max_nodes,
            deadline,
            next_deadline_poll: Cell::new(0),
        };''',
    "control construction",
)

text = replace_once(
    text,
    '''struct EngineControl<'a> {
    stop: &'a StopToken,
    max_nodes: Option<u64>,
    deadline: Option<Instant>,
}

impl SearchControl for EngineControl<'_> {
    fn should_stop(&self, nodes: u64) -> bool {
        self.stop.is_stopped()
            || self.max_nodes.is_some_and(|limit| nodes >= limit)
            || self
                .deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
    }
}''',
    '''struct EngineControl<'a> {
    stop: &'a StopToken,
    max_nodes: Option<u64>,
    deadline: Option<Instant>,
    next_deadline_poll: Cell<u64>,
}

impl SearchControl for EngineControl<'_> {
    fn should_stop(&self, nodes: u64) -> bool {
        if self.stop.is_stopped() || self.max_nodes.is_some_and(|limit| nodes >= limit) {
            return true;
        }

        let Some(deadline) = self.deadline else {
            return false;
        };
        let next_poll = self.next_deadline_poll.get();
        if nodes < next_poll {
            return false;
        }

        self.next_deadline_poll
            .set(nodes.saturating_add(DEADLINE_POLL_INTERVAL_NODES));
        Instant::now() >= deadline
    }
}''',
    "EngineControl policy",
)

text = replace_once(
    text,
    '''    use super::{
        ClockState, DEFAULT_HASH_MB, Engine, MAX_HASH_MB, MIN_HASH_MB, SearchLimits, StopToken,
    };''',
    '''    use super::{
        ClockState, DEADLINE_POLL_INTERVAL_NODES, DEFAULT_HASH_MB, Engine, EngineControl,
        MAX_HASH_MB, MIN_HASH_MB, SearchLimits, StopToken,
    };
    use chess_search::SearchControl;''',
    "test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn hash_configuration_is_bounded_and_survives_new_game() {''',
    '''    #[test]
    fn timed_control_polls_deadline_only_at_fixed_node_intervals() {
        let stop = StopToken::new();
        let control = EngineControl {
            stop: &stop,
            max_nodes: None,
            deadline: Some(std::time::Instant::now() + Duration::from_secs(60)),
            next_deadline_poll: std::cell::Cell::new(0),
        };

        assert!(!control.should_stop(0));
        assert_eq!(control.next_deadline_poll.get(), DEADLINE_POLL_INTERVAL_NODES);
        assert!(!control.should_stop(DEADLINE_POLL_INTERVAL_NODES - 1));
        assert_eq!(control.next_deadline_poll.get(), DEADLINE_POLL_INTERVAL_NODES);
        assert!(!control.should_stop(DEADLINE_POLL_INTERVAL_NODES));
        assert_eq!(
            control.next_deadline_poll.get(),
            DEADLINE_POLL_INTERVAL_NODES * 2
        );
    }

    #[test]
    fn timed_control_keeps_node_limit_and_external_stop_exact() {
        let stop = StopToken::new();
        let control = EngineControl {
            stop: &stop,
            max_nodes: Some(7),
            deadline: Some(std::time::Instant::now() + Duration::from_secs(60)),
            next_deadline_poll: std::cell::Cell::new(u64::MAX),
        };
        assert!(!control.should_stop(6));
        assert!(control.should_stop(7));

        let stop = StopToken::new();
        let control = EngineControl {
            stop: &stop,
            max_nodes: None,
            deadline: Some(std::time::Instant::now() + Duration::from_secs(60)),
            next_deadline_poll: std::cell::Cell::new(u64::MAX),
        };
        stop.stop();
        assert!(control.should_stop(1));
    }

    #[test]
    fn hash_configuration_is_bounded_and_survives_new_game() {''',
    "deadline polling tests",
)

path.write_text(text)
