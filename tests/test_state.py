"""Tests for core/state.py — StateManager."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.state import EngineState, PendingExperiment, RunRecord, StateManager


@pytest.fixture
def state_dir(tmp_path):
    """Return a temporary directory to use as vault path for state."""
    return tmp_path


def test_fresh_state_creation(state_dir):
    """StateManager should create a fresh state when no file exists."""
    mgr = StateManager(state_dir)

    assert mgr.state.seen_idea_titles == set()
    assert mgr.state.run_history == []
    assert mgr.state.pending_experiments == []
    assert mgr.state.vault_hash == ""
    assert mgr.state.last_run is None


def test_persistence_across_load_save(state_dir):
    """State should persist correctly across save/load cycles."""
    mgr = StateManager(state_dir)

    # Add some data
    mgr.add_seen_titles(["Idea Alpha", "Idea Beta"])
    mgr.add_run_record(
        RunRecord(
            run_id="run-001",
            timestamp=datetime(2026, 3, 1, 12, 0),
            ideas_generated=5,
            essays_approved=2,
            essays_rejected=1,
            startups_approved=1,
            startups_rejected=1,
            vault_hash="abc123",
        )
    )
    mgr.state.vault_hash = "abc123"
    mgr.save()

    # Load in a new manager
    mgr2 = StateManager(state_dir)

    assert "Idea Alpha" in mgr2.state.seen_idea_titles
    assert "Idea Beta" in mgr2.state.seen_idea_titles
    assert len(mgr2.state.run_history) == 1
    assert mgr2.state.run_history[0].run_id == "run-001"
    assert mgr2.state.run_history[0].ideas_generated == 5
    assert mgr2.state.vault_hash == "abc123"
    assert mgr2.state.last_run is not None


def test_due_experiment_filtering(state_dir):
    """get_due_experiments should only return past-due experiments."""
    mgr = StateManager(state_dir)

    now = datetime.now()

    # Past-due experiment
    past_due = PendingExperiment(
        slug="past-due",
        created_at=now - timedelta(hours=48),
        eval_after=now - timedelta(hours=24),
        idea_name="Old Idea",
        hypothesis="IF X THEN Y",
        falsification_criteria="If Y < 10",
        experiment_path="/tmp/experiments/past-due",
    )

    # Future experiment
    future = PendingExperiment(
        slug="future",
        created_at=now,
        eval_after=now + timedelta(hours=24),
        idea_name="New Idea",
        hypothesis="IF A THEN B",
        falsification_criteria="If B < 5",
        experiment_path="/tmp/experiments/future",
    )

    mgr.add_pending_experiment(past_due)
    mgr.add_pending_experiment(future)

    due = mgr.get_due_experiments()
    assert len(due) == 1
    assert due[0].slug == "past-due"


def test_title_deduplication(state_dir):
    """Adding the same title twice should not create duplicates."""
    mgr = StateManager(state_dir)

    mgr.add_seen_titles(["Idea One", "Idea Two"])
    mgr.add_seen_titles(["Idea Two", "Idea Three"])

    assert len(mgr.state.seen_idea_titles) == 3
    assert "Idea One" in mgr.state.seen_idea_titles
    assert "Idea Two" in mgr.state.seen_idea_titles
    assert "Idea Three" in mgr.state.seen_idea_titles


def test_corrupt_state_recovery(state_dir):
    """Corrupt state file should be backed up and fresh state returned."""
    state_file = state_dir / ".engine-state.json"
    state_file.write_text("this is not valid json {{{", encoding="utf-8")

    mgr = StateManager(state_dir)

    # Should get fresh state
    assert mgr.state.seen_idea_titles == set()
    # Backup should exist
    assert state_file.with_suffix(".json.bak").exists()


def test_remove_pending_experiment(state_dir):
    """remove_pending_experiment should remove by slug."""
    mgr = StateManager(state_dir)
    now = datetime.now()

    mgr.add_pending_experiment(
        PendingExperiment(
            slug="exp-a",
            created_at=now,
            eval_after=now + timedelta(hours=24),
            idea_name="A",
            hypothesis="H",
            falsification_criteria="F",
            experiment_path="/tmp/a",
        )
    )
    mgr.add_pending_experiment(
        PendingExperiment(
            slug="exp-b",
            created_at=now,
            eval_after=now + timedelta(hours=24),
            idea_name="B",
            hypothesis="H",
            falsification_criteria="F",
            experiment_path="/tmp/b",
        )
    )

    assert len(mgr.state.pending_experiments) == 2
    mgr.remove_pending_experiment("exp-a")
    assert len(mgr.state.pending_experiments) == 1
    assert mgr.state.pending_experiments[0].slug == "exp-b"
