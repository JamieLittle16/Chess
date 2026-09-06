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
+ exact protocol-pinned opening suite
+ explicit engine options
+ recorded machine/tool environment
→ manifest + raw runner log + PGN + UCI log
```

A sample is immutable evidence. Do not append another tournament to an existing result directory and
do not repair an interrupted sample in place. The wrapper therefore refuses a non-empty output
directory.

## 2. Repository protocol

The first finite-time protocol is:

```text
match/protocols/m3-baseline-v1.json
```

It fixes:

- 200 games / 100 opening pairs;
- `10+0.1` time control;
- one concurrent game;
- deterministic seed `20260906`;
- paired colour reversal;
- opening suite `m3-uho-lichess-100-v1`;
- opening SHA-256 `599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1`;
- maximum 300 moves;
- no ponder;
- no tablebases;
- no evaluation-based resign/draw adjudication.

The harness verifies the supplied opening file against the protocol SHA-256 before it creates the
result directory. A different book is therefore a different experiment, not another
`m3-baseline-v1` sample.

The no-score-adjudication restriction is deliberate. The M3 evaluator is material-only, so its
numeric opinion is not credible enough to decide whether tournament games should be truncated as wins
or draws. Baseline games terminate by chess rules or the fixed maximum-move guard.

Changing one of these fields creates a different protocol. Do not silently edit a completed
protocol's meaning while keeping the same `protocol_id`.

## 3. Frozen opening corpus

The vendored corpus is:

```text
match/openings/m3-uho-lichess-100-v1.epd
match/openings/m3-uho-lichess-100-v1.json
```

It is derived from the official Stockfish opening-book repository:

```text
repository: official-stockfish/books
commit:     65815ccdbc7727cd4f6aee252ba8f67fb740e92f
archive:    UHO_Lichess_4852_v1.epd.zip
Git blob:   e439636101786177ece850d3607356891c1cc2cd
archive SHA-256:
            4e298f11e8acfa106babe02968f2e61582145e7874c59284690b20b9650e0e07
upstream uncompressed SHA-384 SRI:
            QHAU1P3LurcJr7UTRI7HZCVFsoYBWC3OTsBqZY/FfQA6VQo3MmECWtByB4gVACW5
upstream positions:
            2,632,036
license:    CC0-1.0
```

The source book is not copied wholesale into this repository. `scripts/build_opening_suite.py` verifies
archive size/SHA-256, ZIP member, upstream uncompressed SRI and source position count, then ranks every
non-empty normalized source position by:

```text
SHA256("Chess/m3-uho-lichess-100-v1" || NUL || EPD-line-bytes)
```

and retains the 100 smallest ranks. The final positions are stored in rank order. This samples across
the entire pinned 2.63M-position source without a runtime RNG or a fragile "first 100 lines" rule.

The derivation script also pins the final corpus hash, so regeneration fails if either the upstream
artifact or the selection result differs.

The normal CI gate does not redownload the 42.9 MB source book. It validates the vendored hash,
metadata, count, uniqueness and rank order in Python, while `chess-core` independently parses all 100
FENs and requires every one to be a legal nonterminal position. The upstream derivation can be rerun
explicitly when auditing the corpus.

## 4. Pairing

Every opening is used as a two-game pair with colours reversed. The generated Fastchess command uses:

```text
-games 2 -repeat
```

and sets a deterministic `-srand` seed. Qualification retains pentanomial pair outcomes rather than
only aggregate W/D/L because the two games from one opening are statistically coupled.

The wrapper deliberately does not pass crash-recovery/resume behaviour for qualification runs. An
engine crash makes that sample failed evidence rather than a tournament to continue and later mistake
for one uninterrupted sample.

## 5. Provenance manifest

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

## 6. Output statuses

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

## 7. Running a qualification match

Build the engine binaries separately so candidate and reference are immutable files during the run.
Then invoke, for example:

```sh
python3 scripts/match_harness.py \
  --candidate /absolute/path/to/candidate \
  --reference /absolute/path/to/reference \
  --fastchess /absolute/path/to/fastchess \
  --openings match/openings/m3-uho-lichess-100-v1.epd \
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

CI tests the repository-owned experiment boundary:

- strict protocol validation;
- exact protocol-pinned opening SHA-256 enforcement;
- opening metadata/count/uniqueness/rank-order checks;
- all 100 openings parsed and checked as nonterminal by `chess-core`;
- paired/seeded command construction;
- forbidden recovery/adjudication flags remaining absent;
- exact file hashing;
- fresh-output-directory enforcement;
- required/wrong openings rejected before output creation;
- dry-run manifest creation with fake executables;
- output artifact hashing.

These qualification tests use only Python's standard library plus the existing Rust chess core.
`./scripts/check.sh` runs them together with the complete Rust gate and deterministic reference-search
benchmark.

## 10. M3 exit

The measurement infrastructure and frozen opening corpus are now defined. M3 closes only when we also
have:

1. a retained completed baseline sample against a named reference;
2. a reported relative result with uncertainty and all provenance evidence.

Only after that control group exists should M4 strength work begin in earnest.
