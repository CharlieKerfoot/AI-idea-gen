"""Tests for core/state.py — StateManager."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.state import (
    EngineState,
    PendingExperiment,
    QuarantinedNote,
    RunRecord,
    StateManager,
    extract_keywords,
)


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


# ── extract_keywords tests ──────────────────────────────────────


def test_extract_keywords_basic():
    """Should extract lowercase words >= 4 chars, excluding stopwords."""
    keywords = extract_keywords("The Quick Brown Fox Jumps Over")
    assert "quick" in keywords
    assert "brown" in keywords
    assert "jumps" in keywords
    assert "over" not in keywords  # stopword
    assert "the" not in keywords  # < 4 chars and stopword
    assert "fox" not in keywords  # < 3 chars


def test_extract_keywords_deduplication():
    """Should not return duplicate keywords."""
    keywords = extract_keywords("hello hello world world testing testing")
    assert keywords.count("hello") == 1
    assert keywords.count("world") == 1
    assert keywords.count("testing") == 1


def test_extract_keywords_splits_on_non_alpha():
    """Should split on non-alpha characters."""
    keywords = extract_keywords("machine-learning is great! AI/ML rocks")
    assert "machine" in keywords
    assert "learning" in keywords
    assert "great" in keywords
    assert "rocks" in keywords


def test_extract_keywords_filters_engine_stopwords():
    """Should filter engine-specific stopwords."""
    keywords = extract_keywords("novel idea approach system generated")
    assert "novel" not in keywords
    assert "approach" not in keywords
    assert "system" not in keywords
    assert "generated" not in keywords


def test_extract_keywords_empty_input():
    """Should handle empty or whitespace-only input."""
    assert extract_keywords("") == []
    assert extract_keywords("   ") == []


# ── Concept tracking tests ──────────────────────────────────────


def test_record_concepts(state_dir):
    """record_concepts should increment keyword frequency counts."""
    mgr = StateManager(state_dir)

    mgr.record_concepts("machine learning transforms everything")
    assert mgr.state.concept_frequencies.get("machine", 0) == 1
    assert mgr.state.concept_frequencies.get("learning", 0) == 1
    assert mgr.state.concept_frequencies.get("transforms", 0) == 1
    assert mgr.state.concept_frequencies.get("everything", 0) == 1

    # Record again — counts should increase
    mgr.record_concepts("machine learning is powerful")
    assert mgr.state.concept_frequencies["machine"] == 2
    assert mgr.state.concept_frequencies["learning"] == 2


def test_get_overused_concepts(state_dir):
    """get_overused_concepts should return concepts above threshold."""
    mgr = StateManager(state_dir)

    # Manually set frequencies
    mgr.state.concept_frequencies = {
        "blockchain": 5,
        "quantum": 4,
        "neural": 2,
        "markets": 1,
    }

    overused = mgr.get_overused_concepts(threshold=3)
    assert "blockchain" in overused
    assert "quantum" in overused
    assert "neural" not in overused
    assert "markets" not in overused
    assert overused["blockchain"] == 5
    assert overused["quantum"] == 4


def test_get_overused_concepts_empty(state_dir):
    """Should return empty dict when no concepts exceed threshold."""
    mgr = StateManager(state_dir)
    mgr.state.concept_frequencies = {"word": 1, "another": 2}
    assert mgr.get_overused_concepts(threshold=3) == {}


def test_concept_frequencies_persist(state_dir):
    """Concept frequencies should survive save/load cycles."""
    mgr = StateManager(state_dir)
    mgr.record_concepts("persistent concept tracking works")
    mgr.save()

    mgr2 = StateManager(state_dir)
    assert mgr2.state.concept_frequencies.get("persistent", 0) == 1
    assert mgr2.state.concept_frequencies.get("concept", 0) == 1
    assert mgr2.state.concept_frequencies.get("tracking", 0) == 1
    assert mgr2.state.concept_frequencies.get("works", 0) == 1


# ── Quarantine lifecycle tests ──────────────────────────────────


def test_quarantine_note(state_dir):
    """quarantine_note should add a note to the quarantine list."""
    mgr = StateManager(state_dir)
    mgr.state.run_count = 5

    mgr.quarantine_note("/vault/essays/test.md", cycles=3)

    assert len(mgr.state.quarantined_notes) == 1
    q = mgr.state.quarantined_notes[0]
    assert q.path == "/vault/essays/test.md"
    assert q.quarantined_at_run == 5
    assert q.release_after_run == 8


def test_get_quarantined_paths(state_dir):
    """get_quarantined_paths should return all quarantined paths."""
    mgr = StateManager(state_dir)
    mgr.state.run_count = 1

    mgr.quarantine_note("/vault/a.md", 3)
    mgr.quarantine_note("/vault/b.md", 3)

    paths = mgr.get_quarantined_paths()
    assert paths == {"/vault/a.md", "/vault/b.md"}


def test_expire_quarantines(state_dir):
    """expire_quarantines should remove notes past their release run."""
    mgr = StateManager(state_dir)

    mgr.state.quarantined_notes = [
        QuarantinedNote(path="/vault/old.md", quarantined_at_run=1, release_after_run=3),
        QuarantinedNote(path="/vault/new.md", quarantined_at_run=3, release_after_run=6),
    ]

    # At run 4, only "old" should expire (release_after_run=3 <= run_count=4)
    mgr.state.run_count = 4
    mgr.expire_quarantines()

    assert len(mgr.state.quarantined_notes) == 1
    assert mgr.state.quarantined_notes[0].path == "/vault/new.md"


def test_quarantine_full_lifecycle(state_dir):
    """Full quarantine lifecycle: add, check, expire over multiple runs."""
    mgr = StateManager(state_dir)

    # Run 1: quarantine a note for 2 cycles
    mgr.increment_run_count()  # run_count = 1
    mgr.quarantine_note("/vault/essay.md", cycles=2)
    assert "/vault/essay.md" in mgr.get_quarantined_paths()

    # Run 2: still quarantined
    mgr.increment_run_count()  # run_count = 2
    mgr.expire_quarantines()
    assert "/vault/essay.md" in mgr.get_quarantined_paths()

    # Run 3: still quarantined (release_after_run=3, so 3 is not > 3)
    mgr.increment_run_count()  # run_count = 3
    mgr.expire_quarantines()
    assert "/vault/essay.md" not in mgr.get_quarantined_paths()


def test_quarantine_persists_across_save_load(state_dir):
    """Quarantined notes should survive save/load cycles."""
    mgr = StateManager(state_dir)
    mgr.state.run_count = 5
    mgr.quarantine_note("/vault/test.md", 3)
    mgr.save()

    mgr2 = StateManager(state_dir)
    assert len(mgr2.state.quarantined_notes) == 1
    assert mgr2.state.quarantined_notes[0].path == "/vault/test.md"
    assert mgr2.state.run_count == 5


def test_increment_run_count(state_dir):
    """increment_run_count should increase run counter."""
    mgr = StateManager(state_dir)
    assert mgr.state.run_count == 0

    mgr.increment_run_count()
    assert mgr.state.run_count == 1

    mgr.increment_run_count()
    assert mgr.state.run_count == 2
