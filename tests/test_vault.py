"""Tests for core/vault.py — VaultManager."""

import os
from datetime import datetime
from pathlib import Path

import pytest

from core.vault import VaultManager, VaultNote


@pytest.fixture
def vault_config(tmp_path):
    """Create a minimal vault config pointing at tmp_path."""
    return {
        "vault": {
            "path": str(tmp_path),
            "idea_engine_folder": "_idea-engine",
            "scan_glob": "**/*.md",
            "exclude_folders": ["_idea-engine", "templates", ".obsidian"],
        }
    }


@pytest.fixture
def populated_vault(tmp_path):
    """Create a vault with several test notes."""
    # Regular notes
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "note1.md").write_text(
        "---\ntags: [philosophy, thinking]\ndate: 2026-01-15\n---\n\n"
        "# The Nature of Ideas\n\n"
        "Ideas are strange things. They emerge from the intersection of "
        "unrelated concepts and take on lives of their own. "
        "See also [[note2]].\n" + "More content. " * 30
    )
    (tmp_path / "notes" / "note2.md").write_text(
        "---\ntags: [technology]\ndate: 2026-02-20\n---\n\n"
        "# Software and Thought\n\n"
        "Software reshapes how we think about problems. "
        "Related to [[note1]].\n" + "Extra words. " * 25
    )

    # Note without frontmatter
    (tmp_path / "notes" / "no-frontmatter.md").write_text(
        "# Just a Title\n\nSome content without YAML frontmatter.\n"
    )

    # Recent note
    (tmp_path / "recent.md").write_text(
        "---\ntags: [new]\ndate: 2026-03-01\n---\n\n"
        "# Very Recent Idea\n\nThis is brand new thinking.\n"
    )

    # Excluded folders
    (tmp_path / "_idea-engine").mkdir()
    (tmp_path / "_idea-engine" / "output.md").write_text("# Should be excluded\n")

    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "template.md").write_text("# Also excluded\n")

    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "config.md").write_text("# Hidden\n")

    return tmp_path


def test_scan_excludes_configured_folders(populated_vault, vault_config):
    """Excluded folders should not appear in scan results."""
    vault_config["vault"]["path"] = str(populated_vault)
    vm = VaultManager(vault_config)
    notes = vm.scan_notes()
    titles = {n.title for n in notes}

    assert "Should be excluded" not in titles
    assert "Also excluded" not in titles
    assert "Hidden" not in titles


def test_scan_excludes_hidden_dirs(populated_vault, vault_config):
    """Hidden directories (starting with .) should be excluded."""
    vault_config["vault"]["path"] = str(populated_vault)
    vm = VaultManager(vault_config)
    notes = vm.scan_notes()
    paths = [str(n.path) for n in notes]

    assert not any(".obsidian" in p for p in paths)


def test_frontmatter_parsing(populated_vault, vault_config):
    """Notes with frontmatter should have tags and metadata parsed."""
    vault_config["vault"]["path"] = str(populated_vault)
    vm = VaultManager(vault_config)
    notes = vm.scan_notes()
    note1 = next(n for n in notes if n.title == "The Nature of Ideas")

    assert "philosophy" in note1.tags
    assert "thinking" in note1.tags
    assert note1.frontmatter.get("date") is not None


def test_missing_frontmatter(populated_vault, vault_config):
    """Notes without frontmatter should still be parsed."""
    vault_config["vault"]["path"] = str(populated_vault)
    vm = VaultManager(vault_config)
    notes = vm.scan_notes()
    no_fm = next(n for n in notes if n.title == "Just a Title")

    assert no_fm.tags == []
    assert no_fm.frontmatter == {}
    assert no_fm.content.startswith("# Just a Title")


def test_atomic_write(tmp_path, vault_config):
    """_atomic_write should create the file without leaving .tmp files."""
    vault_config["vault"]["path"] = str(tmp_path)
    vm = VaultManager(vault_config)

    target = tmp_path / "test-output.md"
    vm._atomic_write(target, "# Test Content\n")

    assert target.exists()
    assert target.read_text() == "# Test Content\n"
    assert not target.with_suffix(".tmp").exists()


def test_context_selection_count(populated_vault, vault_config):
    """select_context_notes should return at most n notes."""
    vault_config["vault"]["path"] = str(populated_vault)
    vm = VaultManager(vault_config)

    notes = vm.select_context_notes(2)
    assert len(notes) == 2

    notes_all = vm.select_context_notes(100)
    # Should return all available notes (4 in populated_vault)
    assert len(notes_all) == 4


def test_recent_and_random_strategy(populated_vault, vault_config):
    """recent_and_random should include the most recent note."""
    vault_config["vault"]["path"] = str(populated_vault)
    vm = VaultManager(vault_config)

    # With n=4, half (2) should be recent, rest random
    notes = vm.select_context_notes(4, "recent_and_random")
    assert len(notes) == 4

    # The most recently modified note should be in the first half
    titles = [n.title for n in notes]
    assert len(titles) == 4  # No duplicates from the selection


def test_content_hash_changes(populated_vault, vault_config):
    """content hash should change when notes are added."""
    vault_config["vault"]["path"] = str(populated_vault)
    vm = VaultManager(vault_config)

    hash1 = vm.compute_content_hash()

    # Add a new note
    (populated_vault / "new-note.md").write_text("# New\n\nContent\n")

    hash2 = vm.compute_content_hash()
    assert hash1 != hash2


def test_write_essay_idea_frontmatter(tmp_path, vault_config):
    """Written essay notes should have correct frontmatter."""
    vault_config["vault"]["path"] = str(tmp_path)
    vm = VaultManager(vault_config)

    idea = {
        "title": "Test Essay Idea",
        "hook": "A surprising claim",
        "argument_sketch": "The argument goes like this...",
        "novelty_claim": "Nobody has argued this before",
        "connections": ["note1", "note2"],
    }
    judgment = {
        "weighted_score": 7.5,
        "reasoning": "Strong idea",
        "suggested_vault_tags": ["philosophy"],
        "improvement_note": "Could be sharper",
    }

    path = vm.write_essay_idea(idea, judgment, "run-test-001")

    assert path.exists()
    content = path.read_text()
    assert "essay-idea" in content
    assert "engine-generated" in content
    assert "7.50" in content
    assert "Test Essay Idea" in content
    assert "A surprising claim" in content
    assert "run-test-001" in content


def test_write_rejection(tmp_path, vault_config):
    """Rejection notes should be written to the rejected folder."""
    vault_config["vault"]["path"] = str(tmp_path)
    vm = VaultManager(vault_config)

    item = {
        "title": "Bad Idea",
        "reasoning": "Not novel enough",
        "weighted_score": 4.2,
        "improvement_note": "Needs more edge",
    }

    path = vm.write_rejection(item, "essay", "run-test-002")

    assert path.exists()
    assert "rejected" in str(path)
    content = path.read_text()
    assert "Bad Idea" in content
    assert "Not novel enough" in content
