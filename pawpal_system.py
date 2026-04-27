"""
PawPal+ Logic Layer
Backend classes for pet care scheduling.
"""

import json
import os
import re
from datetime import date, timedelta

# Maps preferred_time strings to sort order (morning first, anytime last)
_TIME_ORDER = {"morning": 0, "afternoon": 1, "evening": 2, "anytime": 3}

# Urgency bonus added to a task's weighted score based on its category.
# Medication and feeding are safety-critical; grooming/enrichment are discretionary.
_CATEGORY_WEIGHT = {
    "medication": 30,
    "feeding":    20,
    "hygiene":    15,
    "walk":       10,
    "grooming":    5,
    "enrichment":  5,
}

VALID_CATEGORIES = set(_CATEGORY_WEIGHT.keys())
VALID_PREFERRED_TIMES = set(_TIME_ORDER.keys())
VALID_FREQUENCIES = {"once", "daily", "weekly"}


def normalize_category(category: str) -> str:
    """Normalize category text and return a valid category value."""
    if category is None:
        raise ValueError("Category is required.")
    synonyms = {
        "meds": "medication",
        "medicine": "medication",
        "pill": "medication",
        "bathroom": "hygiene",
        "cleaning": "hygiene",
        "clean": "hygiene",
        "play": "enrichment",
        "exercise": "walk",
        "food": "feeding",
        "feed": "feeding",
        "bath": "grooming",
    }
    normalized = category.strip().lower()
    normalized = synonyms.get(normalized, normalized)
    if normalized not in VALID_CATEGORIES:
        raise ValueError(f"Unsupported category: {category}")
    return normalized


def normalize_preferred_time(preferred_time: str) -> str:
    """Normalize preferred time slot text to a valid value."""
    if preferred_time is None:
        return "anytime"
    synonyms = {
        "night": "evening",
        "tonight": "evening",
        "noon": "afternoon",
        "am": "morning",
        "pm": "evening",
    }
    normalized = preferred_time.strip().lower()
    normalized = synonyms.get(normalized, normalized)
    if normalized not in VALID_PREFERRED_TIMES:
        raise ValueError(f"Unsupported preferred_time: {preferred_time}")
    return normalized


def normalize_frequency(frequency: str) -> str:
    """Normalize recurrence frequency to once, daily, or weekly."""
    if frequency is None:
        return "once"
    synonyms = {
        "everyday": "daily",
        "each day": "daily",
        "every day": "daily",
    }
    normalized = frequency.strip().lower()
    normalized = synonyms.get(normalized, normalized)
    if normalized not in VALID_FREQUENCIES:
        raise ValueError(f"Unsupported frequency: {frequency}")
    return normalized


def normalize_time(time_str: str) -> str | None:
    """Validate and normalize HH:MM input, or return None."""
    if not time_str:
        return None
    cleaned = time_str.strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", cleaned):
        raise ValueError(f"Invalid time format: {time_str}")
    hour, minute = cleaned.split(":")
    h = int(hour)
    m = int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid time value: {time_str}")
    return f"{h:02d}:{m:02d}"


class Task:
    """Represents a single pet care activity with duration, priority, and completion state."""

    def __init__(self, name: str, duration_minutes: int, priority: int, category: str,
                 preferred_time: str = "anytime", frequency: str = "once",
                 time: str = None, due_date: date = None):
        self.name = name
        self.duration_minutes = duration_minutes
        self.priority = priority          # 1 (low) to 5 (high)
        self.category = category          # e.g. "walk", "feeding", "medication"
        self.preferred_time = preferred_time  # "morning", "afternoon", "evening", "anytime"
        self.frequency = frequency        # "once", "daily", "weekly"
        self.time = time                  # exact time string, e.g. "08:00" (used for conflict detection)
        self.due_date = due_date or date.today()
        self.completed = False
        self.pet_name = None              # set automatically by Pet.add_task()

    @property
    def priority_label(self) -> str:
        """Return a human-readable priority label: Low (1-2), Medium (3), High (4-5)."""
        if self.priority >= 4:
            return "High"
        if self.priority == 3:
            return "Medium"
        return "Low"

    @property
    def priority_emoji(self) -> str:
        """Return a color-dot emoji for the task's priority level."""
        return {"High": "🔴", "Medium": "🟡", "Low": "🟢"}[self.priority_label]

    def get_priority_score(self) -> int:
        """Return the numeric priority of this task."""
        return self.priority

    def compute_weighted_score(self) -> int:
        """Return a composite urgency score combining priority, category, and due-date status.

        Formula:
            base      = priority × 10          (range 10–50)
            category  = _CATEGORY_WEIGHT bonus  (0–30, e.g. medication=30, feeding=20)
            overdue   = +25 if due_date < today, else 0
            recurring = +5 for daily, +3 for weekly, 0 for once

        Higher scores surface more urgent tasks first in generate_weighted_plan().
        """
        base = self.priority * 10
        category_bonus = _CATEGORY_WEIGHT.get(self.category, 0)
        overdue_bonus = 25 if self.due_date < date.today() else 0
        recurrence_bonus = {"daily": 5, "weekly": 3}.get(self.frequency, 0)
        return base + category_bonus + overdue_bonus + recurrence_bonus

    def is_schedulable(self, available_minutes: int) -> bool:
        """Return True if this task's duration fits within the given available minutes."""
        return self.duration_minutes <= available_minutes

    def mark_complete(self) -> "Task | None":
        """Mark this task as completed.

        For recurring tasks (daily or weekly), creates and returns a new Task
        instance scheduled for the next occurrence. Returns None for one-time tasks.
        """
        self.completed = True
        if self.frequency == "daily":
            next_task = self._clone_for_date(self.due_date + timedelta(days=1))
            return next_task
        if self.frequency == "weekly":
            next_task = self._clone_for_date(self.due_date + timedelta(weeks=1))
            return next_task
        return None

    def _clone_for_date(self, new_due: date) -> "Task":
        """Return a fresh, incomplete copy of this task with an updated due date."""
        clone = Task(
            name=self.name,
            duration_minutes=self.duration_minutes,
            priority=self.priority,
            category=self.category,
            preferred_time=self.preferred_time,
            frequency=self.frequency,
            time=self.time,
            due_date=new_due,
        )
        clone.pet_name = self.pet_name
        return clone

    def __repr__(self) -> str:
        """Return a readable string representation of the task."""
        status = "done" if self.completed else "pending"
        time_str = f" @ {self.time}" if self.time else ""
        freq_str = f" [{self.frequency}]" if self.frequency != "once" else ""
        return (f"[{self.preferred_time}{time_str}] {self.name} "
                f"({self.duration_minutes} min, priority {self.priority}){freq_str} [{status}]")


class Pet:
    """Stores a pet's profile and the list of care tasks assigned to it."""

    def __init__(self, name: str, breed: str, age: int, special_needs: list = None):
        self.name = name
        self.breed = breed
        self.age = age
        self.special_needs = special_needs or []
        self.tasks: list[Task] = []

    def add_task(self, task: Task) -> None:
        """Append a Task to this pet's task list and tag it with this pet's name."""
        task.pet_name = self.name
        self.tasks.append(task)

    def get_tasks(self) -> list[Task]:
        """Return all tasks associated with this pet."""
        return self.tasks


class Owner:
    """Manages one or more pets and tracks daily time available for pet care."""

    def __init__(self, name: str, available_minutes: int, preferences: list = None):
        self.name = name
        self.available_minutes = available_minutes
        self.preferences = preferences or []
        self.pets: list[Pet] = []

    def add_pet(self, pet: Pet) -> None:
        """Register a pet under this owner."""
        self.pets.append(pet)

    def get_available_time(self) -> int:
        """Return total daily minutes the owner has available for pet care."""
        return self.available_minutes

    def get_all_tasks(self) -> list[Task]:
        """Return a combined list of every task across all owned pets."""
        all_tasks = []
        for pet in self.pets:
            all_tasks.extend(pet.get_tasks())
        return all_tasks

    def get_pet(self, name: str) -> "Pet | None":
        """Return the Pet with the given name, or None if not found."""
        for pet in self.pets:
            if pet.name == name:
                return pet
        return None

    def save_to_json(self, path: str = "data.json") -> None:
        """Serialize the owner, all pets, and all tasks to a JSON file."""
        data = {
            "name": self.name,
            "available_minutes": self.available_minutes,
            "preferences": self.preferences,
            "pets": [
                {
                    "name": pet.name,
                    "breed": pet.breed,
                    "age": pet.age,
                    "special_needs": pet.special_needs,
                    "tasks": [
                        {
                            "name": t.name,
                            "duration_minutes": t.duration_minutes,
                            "priority": t.priority,
                            "category": t.category,
                            "preferred_time": t.preferred_time,
                            "frequency": t.frequency,
                            "time": t.time,
                            "due_date": t.due_date.isoformat(),
                            "completed": t.completed,
                        }
                        for t in pet.get_tasks()
                    ],
                }
                for pet in self.pets
            ],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load_from_json(cls, path: str = "data.json") -> "Owner | None":
        """Load an Owner (with pets and tasks) from a JSON file.

        Returns None if the file does not exist.
        """
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        owner = cls(
            name=data["name"],
            available_minutes=data["available_minutes"],
            preferences=data.get("preferences", []),
        )
        for pet_data in data.get("pets", []):
            pet = Pet(
                name=pet_data["name"],
                breed=pet_data["breed"],
                age=pet_data["age"],
                special_needs=pet_data.get("special_needs", []),
            )
            for t_data in pet_data.get("tasks", []):
                task = Task(
                    name=t_data["name"],
                    duration_minutes=t_data["duration_minutes"],
                    priority=t_data["priority"],
                    category=t_data["category"],
                    preferred_time=t_data.get("preferred_time", "anytime"),
                    frequency=t_data.get("frequency", "once"),
                    time=t_data.get("time"),
                    due_date=date.fromisoformat(t_data["due_date"]),
                )
                task.completed = t_data.get("completed", False)
                pet.add_task(task)
            owner.add_pet(pet)
        return owner


class Scheduler:
    """Generates a prioritized daily care plan that fits within the owner's available time."""

    def __init__(self, owner: Owner):
        self.owner = owner
        self.total_minutes: int = owner.available_minutes

    def filter_by_time(self, minutes: int) -> list[Task]:
        """Return tasks from all pets whose duration fits within the given minutes."""
        return [t for t in self.owner.get_all_tasks() if t.is_schedulable(minutes)]

    def sort_by_priority(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted from highest to lowest priority score."""
        return sorted(tasks, key=lambda t: t.get_priority_score(), reverse=True)

    def sort_by_priority_then_time(self, tasks: list[Task]) -> list[Task]:
        """Sort tasks by priority descending, then by time-of-day slot ascending.

        High-priority tasks appear first; within the same priority level tasks
        are ordered morning → afternoon → evening → anytime.
        """
        return sorted(
            tasks,
            key=lambda t: (-t.get_priority_score(), _TIME_ORDER.get(t.preferred_time, 99)),
        )

    def sort_by_time(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted by preferred_time (morning → afternoon → evening → anytime).

        Tasks sharing the same time-of-day slot are then sorted by priority descending
        so the most important task within a slot appears first.
        """
        return sorted(
            tasks,
            key=lambda t: (_TIME_ORDER.get(t.preferred_time, 99), -t.priority),
        )

    def filter_tasks(self, completed: bool = None, pet_name: str = None) -> list[Task]:
        """Return tasks optionally filtered by completion status and/or pet name.

        Args:
            completed: If True, return only completed tasks. If False, return only
                       pending tasks. If None (default), no completion filter is applied.
            pet_name:  If provided, return only tasks belonging to this pet.
                       If None (default), tasks from all pets are included.
        """
        tasks = self.owner.get_all_tasks()
        if completed is not None:
            tasks = [t for t in tasks if t.completed == completed]
        if pet_name is not None:
            tasks = [t for t in tasks if t.pet_name == pet_name]
        return tasks

    def detect_conflicts(self) -> list[str]:
        """Detect tasks scheduled at the exact same time and return warning messages.

        Only considers tasks that have an explicit time string (e.g. "09:00").
        Returns a list of warning strings — one per conflict pair — rather than
        raising an exception, so the rest of the schedule is unaffected.
        """
        warnings: list[str] = []
        timed_tasks = [t for t in self.owner.get_all_tasks() if t.time is not None and not t.completed]
        seen: dict[str, Task] = {}
        for task in timed_tasks:
            if task.time in seen:
                other = seen[task.time]
                warnings.append(
                    f"CONFLICT: '{task.name}' ({task.pet_name or '?'}) and "
                    f"'{other.name}' ({other.pet_name or '?'}) are both scheduled at {task.time}."
                )
            else:
                seen[task.time] = task
        return warnings

    def mark_task_complete(self, task: Task, pet: Pet) -> "Task | None":
        """Mark a task complete and, if recurring, add the next occurrence to the pet's list.

        Args:
            task: The Task to complete.
            pet:  The Pet that owns the task (needed to attach the next occurrence).

        Returns:
            The newly created next-occurrence Task, or None for one-time tasks.
        """
        next_task = task.mark_complete()
        if next_task is not None:
            pet.add_task(next_task)
        return next_task

    def generate_plan(self) -> list[Task]:
        """Build and return an ordered plan of tasks that fit within available time."""
        schedulable = self.filter_by_time(self.total_minutes)
        sorted_tasks = self.sort_by_priority(schedulable)

        plan = []
        remaining = self.total_minutes
        for task in sorted_tasks:
            if task.duration_minutes <= remaining:
                plan.append(task)
                remaining -= task.duration_minutes
        return plan

    def generate_weighted_plan(self) -> list[Task]:
        """Build a daily plan ranked by composite weighted score instead of raw priority.

        Uses Task.compute_weighted_score() which factors in:
          - User-assigned priority (1–5)
          - Category urgency (medication > feeding > hygiene > walk > grooming/enrichment)
          - Whether the task is overdue (due_date earlier than today)
          - Recurrence frequency (daily tasks get a small boost over weekly or one-time)

        This ensures, for example, that an overdue priority-3 medication outranks
        a non-urgent priority-4 grooming session in the final plan.
        """
        pending = [t for t in self.owner.get_all_tasks() if not t.completed]
        ranked = sorted(pending, key=lambda t: t.compute_weighted_score(), reverse=True)

        plan = []
        remaining = self.total_minutes
        for task in ranked:
            if task.duration_minutes <= remaining:
                plan.append(task)
                remaining -= task.duration_minutes
        return plan

    def explain_plan(self, plan: list[Task]) -> str:
        """Return a plain-English explanation of why the plan was chosen."""
        if not plan:
            return "No tasks could be scheduled within the available time."

        total_scheduled = sum(t.duration_minutes for t in plan)
        lines = [
            f"Plan for {self.owner.name} ({self.total_minutes} min available, {total_scheduled} min scheduled):",
            ""
        ]
        for i, task in enumerate(plan, 1):
            lines.append(f"  {i}. {task.name} — {task.duration_minutes} min | priority {task.priority} | {task.preferred_time}")

        skipped = [t for t in self.owner.get_all_tasks() if t not in plan]
        if skipped:
            lines.append("")
            lines.append("Skipped (insufficient time):")
            for task in skipped:
                lines.append(f"  - {task.name} ({task.duration_minutes} min)")

        return "\n".join(lines)


def create_validated_task(
    name: str,
    duration_minutes: int,
    priority: int,
    category: str,
    preferred_time: str = "anytime",
    frequency: str = "once",
    time: str = None,
    due_date: date = None,
) -> Task:
    """Create a Task after validating and normalizing user-provided fields."""
    if not name or not name.strip():
        raise ValueError("Task name is required.")
    if int(duration_minutes) <= 0:
        raise ValueError("Duration must be positive.")
    if not (1 <= int(priority) <= 5):
        raise ValueError("Priority must be between 1 and 5.")

    return Task(
        name=name.strip(),
        duration_minutes=int(duration_minutes),
        priority=int(priority),
        category=normalize_category(category),
        preferred_time=normalize_preferred_time(preferred_time),
        frequency=normalize_frequency(frequency),
        time=normalize_time(time),
        due_date=due_date,
    )
