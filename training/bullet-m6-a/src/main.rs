use std::{env, path::PathBuf};

use bullet::{
    game::inputs::Chess768,
    nn::optimiser::AdamW,
    trainer::{
        save::SavedFormat,
        schedule::{TrainingSchedule, TrainingSteps, lr, wdl},
        settings::LocalSettings,
    },
    value::{ValueTrainerBuilder, loader},
};

const HIDDEN_SIZE: usize = 512;
const EVAL_SCALE: i32 = 400;
const QA: i16 = 255;
const QB: i16 = 64;
const BATCH_SIZE: usize = 16_384;
const DEFAULT_BATCHES_PER_SUPERBATCH: usize = 1_526;
const DEFAULT_SUPERBATCHES: usize = 8;
const WDL_PROPORTION: f32 = 0.75;
const INITIAL_LR: f32 = 0.001;
const FINAL_LR: f32 = 0.000_002_43;

#[derive(Clone, Copy, Debug)]
enum DataFormat {
    Viri,
    Stockfish,
    Bullet,
}

impl DataFormat {
    fn parse(value: &str) -> Result<Self, String> {
        match value {
            "viri" => Ok(Self::Viri),
            "sf" | "stockfish" => Ok(Self::Stockfish),
            "bullet" => Ok(Self::Bullet),
            other => Err(format!("unsupported data format: {other}")),
        }
    }
}

#[derive(Debug)]
struct Args {
    format: DataFormat,
    data_path: PathBuf,
    output_dir: PathBuf,
    superbatches: usize,
    batches_per_superbatch: usize,
    loader_threads: usize,
    buffer_size_mb: usize,
}

impl Args {
    fn parse() -> Result<Self, String> {
        let mut args = env::args().skip(1);
        let format = DataFormat::parse(&args.next().ok_or_else(|| usage("missing data format"))?)?;
        let data_path = PathBuf::from(args.next().ok_or_else(|| usage("missing data path"))?);
        let output_dir = PathBuf::from(
            args.next()
                .ok_or_else(|| usage("missing output directory"))?,
        );
        let superbatches = parse_optional_usize(args.next(), DEFAULT_SUPERBATCHES, "superbatches")?;
        let batches_per_superbatch = parse_optional_usize(
            args.next(),
            DEFAULT_BATCHES_PER_SUPERBATCH,
            "batches per superbatch",
        )?;
        if let Some(extra) = args.next() {
            return Err(usage(&format!("unexpected extra argument: {extra}")));
        }

        let loader_threads = env_usize("CHESS_NNUE_LOADER_THREADS", 4)?;
        let buffer_size_mb = env_usize("CHESS_NNUE_BUFFER_MB", 1024)?;

        if superbatches == 0 || batches_per_superbatch == 0 {
            return Err("training steps must be non-zero".to_string());
        }
        if loader_threads == 0 || buffer_size_mb == 0 {
            return Err("loader settings must be non-zero".to_string());
        }

        Ok(Self {
            format,
            data_path,
            output_dir,
            superbatches,
            batches_per_superbatch,
            loader_threads,
            buffer_size_mb,
        })
    }
}

fn usage(reason: &str) -> String {
    format!(
        "{reason}\nusage: chess-bullet-m6-a <viri|sf|bullet> <data> <output-dir> [superbatches] [batches-per-superbatch]"
    )
}

fn parse_optional_usize(
    value: Option<String>,
    default: usize,
    label: &str,
) -> Result<usize, String> {
    match value {
        Some(value) => value
            .parse::<usize>()
            .map_err(|error| format!("invalid {label} {value:?}: {error}")),
        None => Ok(default),
    }
}

fn env_usize(name: &str, default: usize) -> Result<usize, String> {
    match env::var(name) {
        Ok(value) => value
            .parse::<usize>()
            .map_err(|error| format!("invalid {name}={value:?}: {error}")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(format!("could not read {name}: {error}")),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let args = Args::parse()?;
    if !args.data_path.is_file() {
        return Err(format!(
            "training data does not exist: {}",
            args.data_path.display()
        ));
    }
    std::fs::create_dir_all(&args.output_dir)
        .map_err(|error| format!("could not create output directory: {error}"))?;

    println!("Chess M6-A Bullet trainer");
    println!("architecture=(768 -> {HIDDEN_SIZE})x2 -> 1 SCReLU");
    println!("format={:?}", args.format);
    println!("data={}", args.data_path.display());
    println!("output={}", args.output_dir.display());
    println!("superbatches={}", args.superbatches);
    println!("batches_per_superbatch={}", args.batches_per_superbatch);
    println!("batch_size={BATCH_SIZE}");
    println!("wdl_proportion={WDL_PROPORTION}");
    println!("eval_scale={EVAL_SCALE}");

    let mut trainer = ValueTrainerBuilder::default()
        .dual_perspective()
        .optimiser(AdamW)
        .inputs(Chess768)
        .save_format(&[
            SavedFormat::id("l0w").round().quantise::<i16>(QA),
            SavedFormat::id("l0b").round().quantise::<i16>(QA),
            SavedFormat::id("l1w").round().quantise::<i16>(QB),
            SavedFormat::id("l1b").round().quantise::<i16>(QA * QB),
        ])
        .loss_fn(|output, target| output.sigmoid().squared_error(target))
        .build(|builder, stm_inputs, ntm_inputs| {
            let l0 = builder.new_affine("l0", 768, HIDDEN_SIZE);
            let l1 = builder.new_affine("l1", 2 * HIDDEN_SIZE, 1);
            let stm_hidden = l0.forward(stm_inputs).screlu();
            let ntm_hidden = l0.forward(ntm_inputs).screlu();
            l1.forward(stm_hidden.concat(ntm_hidden))
        });

    let schedule = TrainingSchedule {
        net_id: "chess-m6a-768x512".to_string(),
        eval_scale: EVAL_SCALE as f32,
        steps: TrainingSteps {
            batch_size: BATCH_SIZE,
            batches_per_superbatch: args.batches_per_superbatch,
            start_superbatch: 1,
            end_superbatch: args.superbatches,
        },
        wdl_scheduler: wdl::ConstantWDL {
            value: WDL_PROPORTION,
        },
        lr_scheduler: lr::CosineDecayLR {
            initial_lr: INITIAL_LR,
            final_lr: FINAL_LR,
            final_superbatch: args.superbatches,
        },
        save_rate: 1,
    };

    let output_directory = args
        .output_dir
        .to_str()
        .ok_or_else(|| "output path is not valid UTF-8".to_string())?;
    let settings = LocalSettings {
        threads: args.loader_threads,
        test_set: None,
        output_directory,
        batch_queue_size: 64,
    };
    let data_path = args
        .data_path
        .to_str()
        .ok_or_else(|| "data path is not valid UTF-8".to_string())?;

    match args.format {
        DataFormat::Viri => {
            use loader::viribinpack::{Filter, ViriBinpackLoader, ViriFilter};
            let filter = ViriFilter::Builtin(Filter::default());
            let loader =
                ViriBinpackLoader::new(data_path, args.buffer_size_mb, args.loader_threads, filter);
            trainer.run(&schedule, &settings, &loader);
        }
        DataFormat::Stockfish => {
            use loader::sfbinpack::{MoveType, PieceType, SfBinpackLoader, TrainingDataEntry};

            fn filter(entry: &TrainingDataEntry) -> bool {
                entry.ply >= 16
                    && !entry.pos.is_checked(entry.pos.side_to_move())
                    && entry.score.unsigned_abs() <= 10_000
                    && entry.mv.mtype() == MoveType::Normal
                    && entry.pos.piece_at(entry.mv.to()).piece_type() == PieceType::None
            }

            let loader =
                SfBinpackLoader::new(data_path, args.buffer_size_mb, args.loader_threads, filter);
            trainer.run(&schedule, &settings, &loader);
        }
        DataFormat::Bullet => {
            let loader = loader::DirectSequentialDataLoader::new(&[data_path]);
            trainer.run(&schedule, &settings, &loader);
        }
    }

    Ok(())
}
