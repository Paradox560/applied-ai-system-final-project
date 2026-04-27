"""
Tests for PawPal+ core logic.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta
from pawpal_system import Task, Pet, Owner, Scheduler, create_validated_task
from nl_task_parser import parse_prompt_to_candidates, validate_candidate


def test_mark_complete_changes_status():
    """Verify that calling mark_complete() sets the task's completed flag to True."""
    task = Task(name="Morning Walk", duration_minutes=30, priority=5, category="walk")
    assert task.completed is False
    task.mark_complete()
    assert task.completed is True


def test_add_task_increases_pet_task_count():
    """Verify that adding a task to a Pet increases its task count by one."""
    pet = Pet(name="Buddy", breed="Labrador", age=3)
    assert len(pet.get_tasks()) == 0
    pet.add_task(Task(name="Feeding", duration_minutes=10, priority=4, category="feeding"))
    assert len(pet.get_tasks()) == 1


def test_sort_by_time_chronological_order():
    """Verify tasks are returned in chronological order: morning → afternoon → evening → anytime."""
    owner = Owner(name="Alex", available_minutes=120)
    pet = Pet(name="Luna", breed="Beagle", age=2)
    owner.add_pet(pet)

    pet.add_task(Task(name="Evening Stroll", duration_minutes=20, priority=3, category="walk", preferred_time="evening"))
    pet.add_task(Task(name="Anytime Brush", duration_minutes=10, priority=2, category="grooming", preferred_time="anytime"))
    pet.add_task(Task(name="Morning Feed", duration_minutes=10, priority=5, category="feeding", preferred_time="morning"))
    pet.add_task(Task(name="Afternoon Meds", duration_minutes=5, priority=4, category="medication", preferred_time="afternoon"))

    scheduler = Scheduler(owner)
    sorted_tasks = scheduler.sort_by_time(owner.get_all_tasks())
    time_slots = [t.preferred_time for t in sorted_tasks]

    assert time_slots == ["morning", "afternoon", "evening", "anytime"]


def test_sort_by_time_priority_tiebreaker():
    """Within the same time slot, tasks should be ordered by priority descending."""
    owner = Owner(name="Alex", available_minutes=120)
    pet = Pet(name="Luna", breed="Beagle", age=2)
    owner.add_pet(pet)

    pet.add_task(Task(name="Low Priority Morning", duration_minutes=10, priority=1, category="grooming", preferred_time="morning"))
    pet.add_task(Task(name="High Priority Morning", duration_minutes=10, priority=5, category="feeding", preferred_time="morning"))

    scheduler = Scheduler(owner)
    sorted_tasks = scheduler.sort_by_time(owner.get_all_tasks())

    assert sorted_tasks[0].name == "High Priority Morning"
    assert sorted_tasks[1].name == "Low Priority Morning"


def test_daily_recurrence_creates_next_day_task():
    """Marking a daily task complete should create a new task scheduled for the following day."""
    today = date.today()
    owner = Owner(name="Sam", available_minutes=60)
    pet = Pet(name="Rex", breed="Poodle", age=4)
    owner.add_pet(pet)

    daily_task = Task(
        name="Daily Walk",
        duration_minutes=30,
        priority=4,
        category="walk",
        frequency="daily",
        due_date=today,
    )
    pet.add_task(daily_task)

    scheduler = Scheduler(owner)
    next_task = scheduler.mark_task_complete(daily_task, pet)

    assert daily_task.completed is True
    assert next_task is not None
    assert next_task.due_date == today + timedelta(days=1)
    assert next_task.completed is False
    assert next_task.name == "Daily Walk"
    assert next_task in pet.get_tasks()


def test_weekly_recurrence_creates_next_week_task():
    """Marking a weekly task complete should create a new task scheduled for the following week."""
    today = date.today()
    owner = Owner(name="Sam", available_minutes=60)
    pet = Pet(name="Rex", breed="Poodle", age=4)
    owner.add_pet(pet)

    weekly_task = Task(
        name="Weekly Bath",
        duration_minutes=45,
        priority=3,
        category="grooming",
        frequency="weekly",
        due_date=today,
    )
    pet.add_task(weekly_task)

    scheduler = Scheduler(owner)
    next_task = scheduler.mark_task_complete(weekly_task, pet)

    assert next_task is not None
    assert next_task.due_date == today + timedelta(weeks=1)


def test_once_task_returns_no_next_task():
    """Marking a one-time task complete should return None (no recurrence)."""
    owner = Owner(name="Sam", available_minutes=60)
    pet = Pet(name="Rex", breed="Poodle", age=4)
    owner.add_pet(pet)

    once_task = Task(name="Vet Visit", duration_minutes=60, priority=5, category="medical", frequency="once")
    pet.add_task(once_task)

    scheduler = Scheduler(owner)
    next_task = scheduler.mark_task_complete(once_task, pet)

    assert next_task is None


def test_detect_conflicts_flags_duplicate_times():
    """Verify that the Scheduler returns a warning when two tasks share the same time string."""
    owner = Owner(name="Jordan", available_minutes=120)
    pet = Pet(name="Mochi", breed="Shiba Inu", age=1)
    owner.add_pet(pet)

    pet.add_task(Task(name="Morning Walk", duration_minutes=30, priority=5, category="walk", time="08:00"))
    pet.add_task(Task(name="Morning Feed", duration_minutes=10, priority=4, category="feeding", time="08:00"))

    scheduler = Scheduler(owner)
    warnings = scheduler.detect_conflicts()

    assert len(warnings) == 1
    assert "08:00" in warnings[0]
    assert "Morning Walk" in warnings[0] or "Morning Feed" in warnings[0]


def test_detect_conflicts_no_false_positives():
    """Verify that tasks at distinct times produce no conflict warnings."""
    owner = Owner(name="Jordan", available_minutes=120)
    pet = Pet(name="Mochi", breed="Shiba Inu", age=1)
    owner.add_pet(pet)

    pet.add_task(Task(name="Morning Walk", duration_minutes=30, priority=5, category="walk", time="08:00"))
    pet.add_task(Task(name="Afternoon Feed", duration_minutes=10, priority=4, category="feeding", time="12:00"))

    scheduler = Scheduler(owner)
    warnings = scheduler.detect_conflicts()

    assert warnings == []


def test_weighted_score_medication_beats_same_priority_grooming():
    """Medication should outscore grooming at the same priority due to category weight."""
    med = Task(name="Give Pill", duration_minutes=5, priority=3, category="medication")
    groom = Task(name="Brush Coat", duration_minutes=10, priority=3, category="grooming")
    assert med.compute_weighted_score() > groom.compute_weighted_score()


def test_weighted_score_overdue_bonus_applied():
    """An overdue task should receive a +25 bonus on top of its base score."""
    from datetime import date, timedelta
    yesterday = date.today() - timedelta(days=1)
    overdue = Task(name="Vet Visit", duration_minutes=60, priority=2, category="walk", due_date=yesterday)
    normal  = Task(name="Walk",      duration_minutes=30, priority=2, category="walk")
    assert overdue.compute_weighted_score() == normal.compute_weighted_score() + 25


def test_generate_weighted_plan_prefers_medication_over_higher_raw_priority():
    """An overdue medication (priority 3) should appear before grooming (priority 4) in weighted plan."""
    from datetime import date, timedelta
    owner = Owner(name="Alex", available_minutes=60)
    pet = Pet(name="Buddy", breed="Labrador", age=3)
    owner.add_pet(pet)

    overdue_med = Task(
        name="Overdue Pill",
        duration_minutes=5,
        priority=3,
        category="medication",
        due_date=date.today() - timedelta(days=1),
    )
    groom = Task(name="Grooming", duration_minutes=20, priority=4, category="grooming")
    pet.add_task(overdue_med)
    pet.add_task(groom)

    scheduler = Scheduler(owner)
    plan = scheduler.generate_weighted_plan()

    assert plan[0].name == "Overdue Pill"


def test_detect_conflicts_ignores_completed_tasks():
    """Completed tasks should not be considered in conflict detection."""
    owner = Owner(name="Jordan", available_minutes=120)
    pet = Pet(name="Mochi", breed="Shiba Inu", age=1)
    owner.add_pet(pet)

    task1 = Task(name="Morning Walk", duration_minutes=30, priority=5, category="walk", time="08:00")
    task2 = Task(name="Morning Feed", duration_minutes=10, priority=4, category="feeding", time="08:00")
    task1.completed = True  # already done — should be excluded from conflict check
    pet.add_task(task1)
    pet.add_task(task2)

    scheduler = Scheduler(owner)
    warnings = scheduler.detect_conflicts()

    assert warnings == []


def test_parse_single_prompt_extracts_core_fields():
    candidates = parse_prompt_to_candidates("Feed Mochi at 07:30 daily", ["Mochi"])
    assert len(candidates) == 1
    task = candidates[0]
    assert task.pet_name == "Mochi"
    assert task.category == "feeding"
    assert task.frequency == "daily"
    assert task.time == "07:30"


def test_parse_multi_task_prompt_returns_multiple_candidates():
    prompt = "Feed Mochi at 08:00 and walk Mochi for 20 minutes tonight"
    candidates = parse_prompt_to_candidates(prompt, ["Mochi"])
    assert len(candidates) == 2
    assert {candidate.category for candidate in candidates} == {"feeding", "walk"}


def test_parse_prompt_without_pet_requires_confirmation():
    candidates = parse_prompt_to_candidates("Give meds at 09:00", ["Mochi"])
    assert len(candidates) == 1
    ok, message = validate_candidate(candidates[0])
    assert ok is False
    assert "Pet is required" in message


def test_create_validated_task_normalizes_time_and_synonyms():
    task = create_validated_task(
        name="Give meds",
        duration_minutes=10,
        priority=4,
        category="meds",
        preferred_time="tonight",
        frequency="everyday",
        time="7:05",
    )
    assert task.category == "medication"
    assert task.preferred_time == "evening"
    assert task.frequency == "daily"
    assert task.time == "07:05"


def test_create_validated_task_rejects_invalid_time():
    try:
        create_validated_task(
            name="Bad time task",
            duration_minutes=15,
            priority=3,
            category="feeding",
            time="25:00",
        )
    except ValueError as err:
        assert "Invalid time value" in str(err)
    else:
        raise AssertionError("Expected ValueError for invalid time.")
