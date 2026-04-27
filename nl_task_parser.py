"""Natural-language prompt parsing for PawPal task creation."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from pawpal_system import (
    VALID_CATEGORIES,
    create_validated_task,
    normalize_frequency,
    normalize_preferred_time,
    normalize_time,
)


@dataclass
class ParsedTaskCandidate:
    """Structured task extracted from free text before final creation."""

    name: str
    pet_name: str | None
    category: str
    priority: int
    duration_minutes: int
    frequency: str
    preferred_time: str
    time: str | None
    confidence: float
    warnings: list[str]
    needs_confirmation: bool


_CATEGORY_KEYWORDS = {
    "walk": "walk",
    "stroll": "walk",
    "feed": "feeding",
    "feeding": "feeding",
    "food": "feeding",
    "medication": "medication",
    "meds": "medication",
    "pill": "medication",
    "groom": "grooming",
    "brush": "grooming",
    "bath": "grooming",
    "play": "enrichment",
    "enrichment": "enrichment",
    "clean": "hygiene",
    "litter": "hygiene",
    "hygiene": "hygiene",
}

_TIME_WORDS = {
    "morning": "morning",
    "afternoon": "afternoon",
    "evening": "evening",
    "tonight": "evening",
    "noon": "afternoon",
}

_GEMINI_MODEL = "gemini-1.5-flash"


def parse_prompt_to_candidates(prompt: str, pet_names: list[str], use_llm: bool = False) -> list[ParsedTaskCandidate]:
    """Parse one natural-language prompt into one or more task candidates."""
    if not prompt or not prompt.strip():
        return []

    if use_llm:
        llm_candidates = _parse_with_gemini(prompt, pet_names)
        if llm_candidates:
            return llm_candidates

    segments = _split_prompt(prompt)
    candidates: list[ParsedTaskCandidate] = []
    for segment in segments:
        candidate = _parse_segment(segment, pet_names)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def candidate_to_task(candidate: ParsedTaskCandidate):
    """Convert a parsed candidate into a validated Task object."""
    return create_validated_task(
        name=candidate.name,
        duration_minutes=candidate.duration_minutes,
        priority=candidate.priority,
        category=candidate.category,
        preferred_time=candidate.preferred_time,
        frequency=candidate.frequency,
        time=candidate.time,
    )


def _split_prompt(prompt: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", prompt.strip())
    return [part.strip(" ,.") for part in re.split(r"\band\b|;", normalized, flags=re.IGNORECASE) if part.strip(" ,.")]


def _parse_segment(segment: str, pet_names: list[str]) -> ParsedTaskCandidate | None:
    text = segment.lower()
    warnings: list[str] = []
    confidence = 0.5

    pet_name = _extract_pet_name(segment, pet_names)
    if pet_name:
        confidence += 0.2
    else:
        warnings.append("No pet matched; select a pet before adding.")

    category = _extract_category(text)
    if category is None:
        warnings.append("Could not infer category; defaulted to enrichment.")
        category = "enrichment"
    else:
        confidence += 0.15

    name = _extract_task_name(segment, category)
    frequency = _extract_frequency(text)
    preferred_time, exact_time = _extract_time_hints(text)
    duration = _extract_duration(text)
    priority = _extract_priority(text, category)

    if exact_time:
        confidence += 0.1
    if duration:
        confidence += 0.05
    if "defaulted" in " ".join(warnings).lower():
        confidence -= 0.05

    needs_confirmation = bool(warnings) or pet_name is None

    return ParsedTaskCandidate(
        name=name,
        pet_name=pet_name,
        category=category,
        priority=priority,
        duration_minutes=duration,
        frequency=frequency,
        preferred_time=preferred_time,
        time=exact_time,
        confidence=max(0.0, min(1.0, confidence)),
        warnings=warnings,
        needs_confirmation=needs_confirmation,
    )


def _extract_pet_name(segment: str, pet_names: list[str]) -> str | None:
    lower_seg = segment.lower()
    for pet_name in pet_names:
        if pet_name.lower() in lower_seg:
            return pet_name
    return None


def _extract_category(text: str) -> str | None:
    for keyword, category in _CATEGORY_KEYWORDS.items():
        if keyword in text:
            return category
    return None


def _extract_task_name(segment: str, category: str) -> str:
    cleaned = segment.strip().rstrip(".")
    if len(cleaned) > 3:
        return cleaned[0].upper() + cleaned[1:]
    return f"{category.title()} task"


def _extract_frequency(text: str) -> str:
    if "daily" in text or "every day" in text or "everyday" in text:
        return normalize_frequency("daily")
    if "weekly" in text or "every week" in text:
        return normalize_frequency("weekly")
    return normalize_frequency("once")


def _extract_time_hints(text: str) -> tuple[str, str | None]:
    explicit = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    exact_time = normalize_time(explicit.group(1)) if explicit else None

    slot = "anytime"
    for key, mapped in _TIME_WORDS.items():
        if key in text:
            slot = mapped
            break
    if exact_time:
        hour = int(exact_time.split(":")[0])
        if hour < 12:
            slot = "morning"
        elif hour < 17:
            slot = "afternoon"
        else:
            slot = "evening"
    return normalize_preferred_time(slot), exact_time


def _extract_duration(text: str) -> int:
    match = re.search(r"\b(\d{1,3})\s*(?:min|mins|minutes)\b", text)
    if match:
        return max(1, int(match.group(1)))
    return 15


def _extract_priority(text: str, category: str) -> int:
    match = re.search(r"\bpriority\s*(\d)\b", text)
    if match:
        return max(1, min(5, int(match.group(1))))
    if any(word in text for word in ("urgent", "asap", "important")):
        return 5
    if category == "medication":
        return 5
    if category == "feeding":
        return 4
    return 3


def validate_candidate(candidate: ParsedTaskCandidate) -> tuple[bool, str]:
    """Sanity-check a candidate for app-level approval UI."""
    if candidate.category not in VALID_CATEGORIES:
        return False, "Category not supported."
    if candidate.pet_name is None:
        return False, "Pet is required."
    return True, "ok"


def _parse_with_gemini(prompt: str, pet_names: list[str]) -> list[ParsedTaskCandidate]:
    """Optionally parse with Gemini when GEMINI_API_KEY is available."""
    api_key = _load_gemini_key()
    if not api_key:
        return []

    llm_prompt = (
        "Extract pet-care tasks from this prompt and return ONLY strict JSON as a list. "
        "Each item must include: name, pet_name, category, priority, duration_minutes, "
        "frequency, preferred_time, time, confidence, warnings. "
        f"Allowed pets: {pet_names}. "
        "Allowed categories: walk, feeding, medication, grooming, enrichment, hygiene. "
        "Allowed frequency: once, daily, weekly. "
        "Allowed preferred_time: morning, afternoon, evening, anytime. "
        "Use null for unresolved pet_name/time. "
        f"Prompt: {prompt}"
    )

    payload = {"contents": [{"parts": [{"text": llm_prompt}]}], "generationConfig": {"temperature": 0.2}}
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={api_key}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []

    text = _extract_text_from_gemini_response(raw)
    if not text:
        return []
    parsed_json = _extract_json_list(text)
    if not isinstance(parsed_json, list):
        return []

    candidates: list[ParsedTaskCandidate] = []
    for row in parsed_json:
        if not isinstance(row, dict):
            continue
        try:
            category = row.get("category", "enrichment")
            frequency = row.get("frequency", "once")
            preferred_time = row.get("preferred_time", "anytime")
            parsed_candidate = ParsedTaskCandidate(
                name=str(row.get("name") or "Untitled task"),
                pet_name=row.get("pet_name"),
                category=category,
                priority=max(1, min(5, int(row.get("priority", 3)))),
                duration_minutes=max(1, int(row.get("duration_minutes", 15))),
                frequency=normalize_frequency(str(frequency)),
                preferred_time=normalize_preferred_time(str(preferred_time)),
                time=normalize_time(row.get("time")),
                confidence=max(0.0, min(1.0, float(row.get("confidence", 0.7)))),
                warnings=[str(w) for w in row.get("warnings", [])] if isinstance(row.get("warnings"), list) else [],
                needs_confirmation=False,
            )
            parsed_candidate.needs_confirmation = bool(parsed_candidate.warnings) or parsed_candidate.pet_name is None
            candidates.append(parsed_candidate)
        except (ValueError, TypeError):
            continue
    return candidates


def _load_gemini_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key.strip()
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return None
    try:
        with open(env_path, encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _extract_text_from_gemini_response(raw: dict) -> str:
    candidates = raw.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    return "\n".join(texts).strip()


def _extract_json_list(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
