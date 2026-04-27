# PawPal+ Final Reflection

## System and Feature Reflection

The final system centers on a natural-language task creation pipeline. A user writes a plain-English prompt, the parser extracts task candidates, a validation layer normalizes values, and a human checkpoint approves or rejects each candidate before it is stored. This keeps the project useful in day-to-day use while reducing silent parser errors.

## Limitations and Biases

- The parser is rule-based and English-first, so phrasing outside expected patterns can reduce extraction quality.
- It currently favors explicit pet names, task keywords, and `HH:MM` times, which biases the system toward users with structured prompts.
- Time understanding is intentionally narrow (`morning/afternoon/evening` and exact `HH:MM`), so nuanced temporal language (for example, "after dinner tomorrow") is under-supported.

## Misuse Risks and Mitigations

Potential misuse:
- A user could try to create many vague tasks quickly, producing incorrect schedules.
- A user could assume parsed tasks are always correct and skip review.

Mitigations:
- Candidates with unresolved fields are marked with warnings and require user confirmation.
- Unsupported values fail fast with explicit errors rather than silently persisting.
- A human review checkpoint is mandatory before parsed tasks are added.

## Reliability Testing Surprises

The biggest surprise was how often prompts are semantically clear to humans but still ambiguous for extraction ("Give meds at 9"). Reliability improved noticeably after adding:
- strict normalization rules for category/frequency/time,
- explicit unresolved-candidate handling,
- and a predefined evaluation harness that surfaces ambiguous-case counts.

## AI Collaboration: Helpful and Flawed Suggestions

Helpful suggestion:
- AI proposed a staged flow (`parse -> validate -> review -> create`) instead of direct auto-write, which made the system safer and easier to debug.

Flawed suggestion:
- AI initially assumed unresolved pet references could default to the first pet. That was rejected because it can create dangerous mis-assignments for medication/feed tasks. The fix was to require confirmation when pet resolution fails.

## What I Would Improve Next

- Add overlap-based conflict detection (start/end time windows instead of exact time-string collisions).
- Add lightweight intent confidence calibration against a larger prompt set.
- Add in-UI candidate editing controls before approval so users can correct fields without re-prompting.
