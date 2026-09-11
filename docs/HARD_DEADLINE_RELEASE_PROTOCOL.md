# Hard-deadline release protocol

This exists because the final AI Chessathon submission window on 2026-09-11 was mishandled: a candidate package had already been built, but artifact handoff was delayed while validation continued. Under a hard cutoff, delivery must take priority over further analysis.

## Non-negotiable rule

When a user states a hard submission deadline or says there are <=5 minutes remaining, **artifact handoff comes before further qualification** unless the artifact is known to be corrupt or non-runnable.

If the user explicitly says "give me the file now, then check", that ordering is absolute.

## T-10 minutes

- Freeze the strongest already-qualified build as the safe fallback.
- Build/package every live candidate immediately, in parallel with testing.
- Record filename and SHA-256 as soon as each package exists.
- Keep the safe fallback downloadable at all times.

## T-5 minutes

- Stop starting long qualification work.
- Hand off the strongest available candidate artifact immediately, clearly labelled with its current confidence level.
- Also provide the known-safe fallback if it differs.
- Continue checks only after the user has the files.

## T-2 minutes

- No new experiments.
- No repackaging unless required for validity.
- No waiting for CI results before handoff.
- Deliver the existing artifact first; report validation status second.

## Evidence labels

Use one of these labels, without delaying delivery:

- **QUALIFIED**: passed the intended A/B and integrity checks.
- **CANDIDATE**: runnable/package-valid but qualification incomplete.
- **FALLBACK**: previously qualified safe build.

Never imply that an unqualified candidate is proven stronger.

## AI operating rule

The assistant must not substitute its own preferred validation order for an explicit user deadline. Under deadline pressure, reversibility matters: giving the user a candidate preserves their option to submit it; withholding it destroys that option permanently.

## 2026-09-11 lesson

ROOT4+gate32 had been packaged before the final deadline. It should have been handed off immediately when requested, with ROOT4 retained as the safe fallback, while benchmark/selfplay continued separately. The eventual benchmark evidence actually favoured keeping ROOT4 overall, but that does not excuse withholding the option from the user.
