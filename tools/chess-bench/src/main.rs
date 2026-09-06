use chess_bench::run_reference_suite;

fn main() {
    let report = run_reference_suite();
    println!("suite {}", report.suite);
    for case in &report.cases {
        let best_move = case
            .best_move_raw
            .map_or_else(|| "none".to_owned(), |raw| format!("0x{raw:04x}"));
        println!(
            "case {} depth {} score {} nodes {} tt_hits {} bestmove {}",
            case.name, case.depth, case.score, case.nodes, case.tt_hits, best_move
        );
    }
    println!("signature 0x{:016x}", report.signature);
}
