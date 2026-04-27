"""Evaluation harness for natural-language task parsing."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nl_task_parser import parse_prompt_to_candidates, validate_candidate


TEST_CASES = [
    {
        "prompt": "Feed Mochi at 07:30 daily",
        "pets": ["Mochi"],
        "expected_count": 1,
        "expected_categories": {"feeding"},
    },
    {
        "prompt": "Walk Mochi for 25 minutes tonight and clean litter for Mochi",
        "pets": ["Mochi"],
        "expected_count": 2,
        "expected_categories": {"walk", "hygiene"},
    },
    {
        "prompt": "Give meds at 09:00",
        "pets": ["Mochi"],
        "expected_count": 1,
        "expected_categories": {"medication"},
    },
]


def run_evaluation() -> None:
    total = len(TEST_CASES)
    pass_count = 0
    total_confidence = 0.0
    unresolved_candidates = 0

    for idx, case in enumerate(TEST_CASES, start=1):
        candidates = parse_prompt_to_candidates(case["prompt"], case["pets"])
        count_ok = len(candidates) == case["expected_count"]
        categories = {candidate.category for candidate in candidates}
        category_ok = categories == case["expected_categories"]

        valid_count = 0
        for candidate in candidates:
            total_confidence += candidate.confidence
            ok, _ = validate_candidate(candidate)
            if ok:
                valid_count += 1
            else:
                unresolved_candidates += 1

        case_pass = count_ok and category_ok
        if case_pass:
            pass_count += 1

        print(
            f"Case {idx}: {'PASS' if case_pass else 'FAIL'} | "
            f"count={len(candidates)} expected={case['expected_count']} | "
            f"categories={sorted(categories)} expected={sorted(case['expected_categories'])} | "
            f"validated={valid_count}/{len(candidates)}"
        )

    average_confidence = total_confidence / max(1, sum(len(parse_prompt_to_candidates(c["prompt"], c["pets"])) for c in TEST_CASES))
    print("-" * 80)
    print(f"Summary: {pass_count}/{total} cases passed")
    print(f"Average confidence: {average_confidence:.2f}")
    print(f"Unresolved candidates: {unresolved_candidates}")


if __name__ == "__main__":
    run_evaluation()
