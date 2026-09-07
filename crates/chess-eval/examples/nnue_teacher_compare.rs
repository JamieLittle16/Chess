use std::{env, fs, process};

use chess_core::Position;
use chess_eval::{evaluate, nnue::network::Network};

const BLEND_STEPS: usize = 16;

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

#[derive(Clone, Copy, Default)]
struct SplitStats {
    classical: ErrorStats,
    nnue: ErrorStats,
    blends: [ErrorStats; BLEND_STEPS + 1],
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

    let mut validation = SplitStats::default();
    let mut holdout = SplitStats::default();
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
        let nnue = network
            .evaluate_full(&position)
            .expect("legal frozen teacher position has both kings");
        let stats = match split {
            "validation" => &mut validation,
            "holdout" => &mut holdout,
            "train" => continue,
            _ => malformed(line_no),
        };
        stats.classical.add(classical, target);
        stats.nnue.add(nnue, target);
        for (step, blend) in stats.blends.iter_mut().enumerate() {
            let prediction = blend_score(classical, nnue, step);
            blend.add(prediction, target);
        }
    }

    assert!(validation.classical.count > 0, "validation split is empty");
    assert!(holdout.classical.count > 0, "holdout split is empty");
    let best_step = (0..=BLEND_STEPS)
        .min_by(|&left, &right| {
            validation.blends[left]
                .mse()
                .total_cmp(&validation.blends[right].mse())
        })
        .expect("blend grid is non-empty");

    println!(
        concat!(
            "{{\"hidden\":{},\"blend_nnue_fraction\":{:.4},",
            "\"validation\":{{\"count\":{},\"classical_mse\":{:.3},\"classical_rmse\":{:.3},",
            "\"nnue_mse\":{:.3},\"nnue_rmse\":{:.3},\"blend_mse\":{:.3},\"blend_rmse\":{:.3}}},",
            "\"holdout\":{{\"count\":{},\"classical_mse\":{:.3},\"classical_rmse\":{:.3},",
            "\"nnue_mse\":{:.3},\"nnue_rmse\":{:.3},\"blend_mse\":{:.3},\"blend_rmse\":{:.3}}}}}"
        ),
        network.hidden(),
        best_step as f64 / BLEND_STEPS as f64,
        validation.classical.count,
        validation.classical.mse(),
        validation.classical.rmse(),
        validation.nnue.mse(),
        validation.nnue.rmse(),
        validation.blends[best_step].mse(),
        validation.blends[best_step].rmse(),
        holdout.classical.count,
        holdout.classical.mse(),
        holdout.classical.rmse(),
        holdout.nnue.mse(),
        holdout.nnue.rmse(),
        holdout.blends[best_step].mse(),
        holdout.blends[best_step].rmse(),
    );
}

fn blend_score(classical: i32, nnue: i32, nnue_steps: usize) -> i32 {
    let classical_steps = BLEND_STEPS - nnue_steps;
    let numerator =
        i64::from(classical) * classical_steps as i64 + i64::from(nnue) * nnue_steps as i64;
    (numerator / BLEND_STEPS as i64) as i32
}

fn usage() -> ! {
    eprintln!("usage: nnue_teacher_compare <network.nnue> <split-target-fen.tsv>");
    process::exit(2)
}

fn malformed(line_no: usize) -> ! {
    eprintln!("malformed teacher TSV line {}", line_no + 1);
    process::exit(2)
}
