# Match Qualification

Status: **M3 measurement boundary**

The match harness exists to make strength claims reproducible. It does not implement chess rules,
search, rating mathematics or tournament adjudication. Those concerns remain in the engine or the
selected external match runner.

The repository-owned layer has one job: define an experiment exactly enough that a later run can be
identified, audited and repeated.

## 1. Qualification unit

One qualification sample is one fresh output directory produced by:

```text
protocol JSON
+ exact Fastchess executable
+ exact candidate executable
+ exact reference executable
+ exact opening suite
+ explicit engine options
+ recorded machine/tool environment
→ manifest + raw runner log + PGN + UCI log
```

A sample is immutable evidence. Do not append another tournament to an existing result directory and
do not repair an interrupted sample in place.

The wrapper therefore refuses a non-empty output directory.

## 2. Repository protocol

The first finite-time protocol is:

```text
match/protocols/m3-baseline-v1.json
```

It currently fixes:

- 200 games / 100 opening pairs;
- `10+0.1` time control;
- one concurrent game;
- deterministic seed `20260906`;
- paired colour reversal;
- a required versioned opening file;
- maximum 300 moves;
- no ponder;
- no tablebases;
- no evaluation-based resign/draw adjudication.

The last restriction is deliberate. The M3 evaluator is material-only, so its numeric opinion is not
credible enough to decide whether tournament games should be truncated as wins or draws. Baseline
games terminate by chess rules or the fixed maximum-move guard.

Changing one of these fields creates a different protocol. Do not silently edit a completed
protocol's meaning while keeping the same `protocol_id`.

## 3. Pairing

Every opening is used as a two-game pair with colours reversed. The generated Fastchess command uses:

```text
-games 2 -repeat
```

and sets a deterministic `-srand` seed. Qualification retains pentanomial pair outcomes rather than
only aggregate W/D/L because the two games from one opening are statistically coupled.

The wrapper deliberately does not pass crash-recovery/resume behaviour for qualification runs. An
engine crash makes that sample failed evidence rather than a tournament to continue and later mistake
for one uninterrupted sample.

## 4. Provenance manifest

Before the match starts, `scripts/match_harness.py` writes `manifest.json` containing:

- protocol fields and SHA-256 of the protocol file;
- Fastchess absolute path, SHA-256, size and reported version;
- candidate absolute path, SHA-256, size, working directory and explicit options;
- reference absolute path, SHA-256, size, working directory and explicit options;
- opening-suite absolute path, SHA-256 and size;
- exact Fastchess argv and shell rendering;
- repository HEAD/branch/dirty state;
- operating system, machine, CPU description, logical CPU count, Python and Rust compiler metadata;
- paths of all output evidence.

After a completed, failed or interrupted run, existing generated artifacts are also SHA-256 identified.
A manifest that says `running` should therefore only describe a match that was genuinely still live
when its process/environment disappeared unexpectedly.

## 5. Output statuses

The manifest lifecycle is explicit:

```text
prepared
  ↓
running
  ├── completed   Fastchess exit code 0
  ├── failed      Fastchess non-zero exit code
  └── interrupted user interruption; child process is stopped first
```

`--dry-run` produces status `dry-run`, prints the exact command and writes the same input provenance
without launching a tournament.

Only `completed` samples are strength evidence. `failed`, `interrupted` and `dry-run` records are
useful diagnostics but must not be mixed into reported match statistics.

## 6. Running a qualification match

Build the engine binaries separately so candidate and reference are immutable files during the run.
Then invoke, for example:

```sh
python3 scripts/match_harness.py \
  --candidate /absolute/path/to/candidate \
  --reference /absolute/path/to/reference \
  --fastchess /absolute/path/to/fastchess \
  --openings /absolute/path/to/openings.epd \
  --output-dir results/m3-baseline/<run-id> \
  --candidate-name candidate@<sha> \
  --reference-name reference@<sha>
```

Use `--dry-run` first when preparing a published experiment. Inspect the generated command and
manifest before spending match time.

If an engine requires a UCI option, make it explicit:

```sh
--candidate-option Hash=64
```

The wrapper maps this to Fastchess `option.Hash=64`. Hidden per-machine engine configuration is not a
valid qualification input.

## 7. Opening suites

The protocol requires an opening suite, but the opening corpus is intentionally a separate versioned
artifact. Its content hash is part of every manifest.

A qualification opening suite should:

- contain legal positions suitable for both engines;
- avoid trivially decided or pathological starts unless the experiment explicitly targets them;
- be large enough that opening choice does not dominate the sample;
- be frozen before inspecting candidate results;
- be used identically for candidate/reference colour pairs.

If the opening corpus changes, report a different opening-suite identity even when the time-control
protocol is otherwise unchanged.

## 8. Reporting strength

The accepted statement is **relative engine Elo under a named protocol**, not an absolute FIDE-like
rating.

A published result should identify at minimum:

```text
candidate:       name + executable hash/revision
reference:       name + executable hash/revision
protocol:        protocol_id + protocol-file hash
openings:        suite name + hash
games/pairs:     completed sample size
time control:    exact protocol value
hardware:        recorded machine/CPU constraints
result:          W/D/L plus paired outcome data
relative Elo:    estimate
uncertainty:     stated interval/method
manifest/PGN:    retained evidence
```

Do not quote an Elo delta without its opponent, protocol and uncertainty. Do not translate the result
into a human chess rating.

## 9. CI boundary

CI does **not** run chess tournaments. Shared runners are unsuitable for stable time-control strength
claims and Fastchess is intentionally not a build dependency.

CI instead tests the repository-owned part of the experiment:

- strict protocol validation;
- paired/seeded command construction;
- forbidden recovery/adjudication flags remaining absent;
- exact file hashing;
- fresh-output-directory enforcement;
- required openings being rejected before output creation;
- dry-run manifest creation with fake executables;
- output artifact hashing.

These tests use only Python's standard library. `./scripts/check.sh` runs the same harness tests plus
the complete Rust gate and deterministic reference-search benchmark.

## 10. M3 exit

The harness itself is not the M3 exit condition. M3 closes only when we have:

1. this reproducible match infrastructure green;
2. a frozen opening suite;
3. a retained completed baseline sample against a named reference;
4. a reported relative result with uncertainty and all provenance evidence.

Only after that control group exists should M4 strength work begin in earnest.
