use std::{env, fs, process};

use chess_core::Position;
use chess_eval::{evaluate, nnue::network::Network};

const SCALE_DENOMINATOR: usize = 16;
const MAX_SCALE_STEPS: usize = 64;

#[derive(Clone, Copy, Default)]
struct ErrorStats {
    count: u64,
    squared_error: f64,
}

impl ErrorStats {
    fn add(&mut self, prediction: i32, target: i32) {
        let error = f64::from(prediction - target);
        self.count += 1;
        self.squared_error += error * error;
    }

    fn mse(self) -> f64 {
        self.squared_error / self.count as f64
    }

    fn rmse(self) -> f64 {
        self.mse().sqrt()
    }
}

fn main() {
    let mut args = env::args().skip(1);
    let network_path = args.next().unwrap_or_else(|| usage());
    let corpus_path = args.next().unwrap_or_else(|| usage());

    let bytes = fs::read(&network_path).unwrap_or_else(|error| {
        eprintln!("failed to read {network_path}: {error}");
        process::exit(2);
    });
    let network = Network::from_bytes(&bytes).unwrap_or_else(|error| {
        eprintln!("failed to load {network_path}: {error}");
        process::exit(2);
    });
    let corpus = fs::read_to_string(&corpus_path).unwrap_or_else(|error| {
        eprintln!("failed to read {corpus_path}: {error}");
        process::exit(2);
    });

    let mut validation_baseline = ErrorStats::default();
    let mut holdout_baseline = ErrorStats::default();
    let mut validation_scaled = [ErrorStats::default(); MAX_SCALE_STEPS + 1];
    let mut holdout_scaled = [ErrorStats::default(); MAX_SCALE_STEPS + 1];

    for (line_no, line) in corpus.lines().enumerate() {
        if line.is_empty() {
            continue;
        }
        let mut fields = line.splitn(3, '\t');
        let split = fields.next().expect("split field exists");
        let target = fields
            .next()
            .unwrap_or_else(|| malformed(line_no))
            .parse::<i32>()
            .unwrap_or_else(|_| malformed(line_no));
        let fen = fields.next().unwrap_or_else(|| malformed(line_no));
        let position = Position::from_fen(fen).unwrap_or_else(|_| malformed(line_no));
        let classical = evaluate(&position);
        let residual = network
            .evaluate_full(&position)
            .expect("legal frozen teacher position has both kings");

        let (baseline, scaled) = match split {
            "validation" => (&mut validation_baseline, &mut validation_scaled),
            "holdout" => (&mut holdout_baseline, &mut holdout_scaled),
            "train" => continue,
            _ => malformed(line_no),
        };
        baseline.add(classical, target);
        for (steps, stats) in scaled.iter_mut().enumerate() {
            stats.add(corrected_score(classical, residual, steps), target);
        }
    }

    assert!(validation_baseline.count > 0, "validation split is empty");
    assert!(holdout_baseline.count > 0, "holdout split is empty");
    let best_steps = (0..=MAX_SCALE_STEPS)
        .min_by(|&left, &right| {
            validation_scaled[left]
                .mse()
                .total_cmp(&validation_scaled[right].mse())
        })
        .expect("residual scale grid is non-empty");

    println!(
        concat!(
            "{{\"hidden\":{},\"selected_residual_scale\":{:.4},",
            "\"validation\":{{\"count\":{},\"classical_mse\":{:.3},\"classical_rmse\":{:.3},",
            "\"corrected_mse\":{:.3},\"corrected_rmse\":{:.3}}},",
            "\"holdout\":{{\"count\":{},\"classical_mse\":{:.3},\"classical_rmse\":{:.3},",
            "\"corrected_mse\":{:.3},\"corrected_rmse\":{:.3}}}}}"
        ),
        network.hidden(),
        best_steps as f64 / SCALE_DENOMINATOR as f64,
        validation_baseline.count,
        validation_baseline.mse(),
        validation_baseline.rmse(),
        validation_scaled[best_steps].mse(),
        validation_scaled[best_steps].rmse(),
        holdout_baseline.count,
        holdout_baseline.mse(),
        holdout_baseline.rmse(),
        holdout_scaled[best_steps].mse(),
        holdout_scaled[best_steps].rmse(),
    );
}

fn corrected_score(classical: i32, residual: i32, scale_steps: usize) -> i32 {
    let correction = i64::from(residual) * scale_steps as i64 / SCALE_DENOMINATOR as i64;
    i64::from(classical)
        .saturating_add(correction)
        .clamp(i64::from(i32::MIN), i64::from(i32::MAX)) as i32
}

fn usage() -> ! {
    eprintln!("usage: nnue_residual_compare <residual-network.nnue> <split-target-fen.tsv>");
    process::exit(2)
}

fn malformed(line_no: usize) -> ! {
    eprintln!("malformed teacher TSV line {}", line_no + 1);
    process::exit(2)
}
