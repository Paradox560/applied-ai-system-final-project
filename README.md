# PawPal+ Natural Language Task Planner

PawPal+ is a Streamlit application that helps pet owners convert natural-language requests into structured care tasks and daily plans. The system combines task parsing, validation, scheduling, and conflict detection so users can go from "Feed Mochi at 7:30 and walk tonight" to an actionable schedule in one flow.

Natural-language parsing supports two modes:
- deterministic parser (default fallback, fully reproducible),
- optional Gemini-assisted extraction when `GEMINI_API_KEY` is available in `.env`.

## Original Project (Modules 1-3)

The original project was PawPal+, a task scheduler for pet care that let users manually enter tasks with duration, priority, and category, then generate a constrained daily plan. It included recurrence support (daily/weekly), conflict detection for exact-time collisions, and filtering by status/pet. This final version keeps those capabilities and adds natural-language task creation as a core behavior.

## Advanced Feature Category

- **Primary:** Agentic Workflow (`prompt -> parse -> validate -> human checkpoint -> create tasks -> schedule`)
- **Secondary reliability support:** testing harness, confidence score display, and safe validation rules

## Architecture Overview

Architecture diagram: `assets/architecture-diagram.md`

Main components:
- **Natural-language parser** (`nl_task_parser.py`) extracts one or more task candidates using optional Gemini + deterministic fallback.
- **Validation/normalization layer** (`create_validated_task` in `pawpal_system.py`) enforces supported categories, times, and recurrence.
- **Human review checkpoint** (`app.py`) shows parsed candidates, confidence, and warnings before task creation.
- **Scheduler and conflict engine** (`Scheduler` in `pawpal_system.py`) produces the final plan and warnings.
- **Evaluation harness** (`scripts/evaluate_nl_tasks.py`) runs predefined prompt cases and prints summary metrics.

## Setup Instructions

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Optional `.env` for Gemini parsing:

```bash
GEMINI_API_KEY=your_key_here
```

Run tests:

```bash
source .venv/bin/activate
python -m pytest
```

Run reliability harness:

```bash
source .venv/bin/activate
python scripts/evaluate_nl_tasks.py
```

## Sample Interactions

### 1) Clear single task
- **Input:** `Feed Mochi at 07:30 daily`
- **Parsed output:** 1 candidate with category `feeding`, frequency `daily`, time `07:30`, confidence near `0.95`
- **Final behavior:** after approval, task is created and included in scheduling

### 2) Multi-task prompt
- **Input:** `Walk Mochi for 25 minutes tonight and clean litter for Mochi`
- **Parsed output:** 2 candidates (`walk`, `hygiene`), each validated and reviewable
- **Final behavior:** both tasks can be approved together and then scheduled

### 3) Ambiguous prompt
- **Input:** `Give meds at 09:00`
- **Parsed output:** candidate with unresolved pet and warning
- **Final behavior:** candidate is flagged for confirmation and not auto-added until resolved

## Design Decisions and Trade-offs

- A deterministic parser was chosen over direct LLM calls to keep behavior reproducible and easier to test.
- Human approval is required before parsed candidates are persisted, reducing silent bad writes.
- Time parsing intentionally accepts only `HH:MM` to prevent format ambiguity.
- Conflict detection still uses exact-time collisions; overlap-based detection remains future work.

## Logging, Guardrails, and Error Handling

- Task creation uses centralized validation (`create_validated_task`) for consistent guardrails.
- Invalid fields raise explicit `ValueError` messages and surface as user warnings in the UI.
- Unresolved candidates are marked with `needs_confirmation` and skipped during approval.

## Testing Summary

- Unit tests now cover scheduling, recurrence, conflicts, and NL parsing behaviors.
- Current test result: `18 passed`.
- Evaluation harness result on predefined prompts: `3/3 cases passed`, `average confidence 0.90`, `1 unresolved candidate` (expected ambiguity case).
- What worked: deterministic extraction and normalization for common phrases.
- What did not fully work: highly implicit prompts still need user confirmation.

## Reflection

This project reinforced that practical AI systems need both intelligence and control points. The strongest design choice was keeping a human checkpoint between parse and persistence, which improved trust without making the system feel slow. The major next step is richer language coverage (for relative dates and overlapping time windows) while preserving reproducibility.