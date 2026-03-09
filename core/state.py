"""Persistent state management for the idea engine."""

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Keyword Extraction ──────────────────────────────────────────

STOPWORDS: set[str] = {
    "that", "this", "with", "from", "have", "been", "were", "will",
    "would", "could", "should", "their", "there", "they", "them",
    "then", "than", "what", "when", "where", "which", "while",
    "about", "after", "before", "between", "into", "through",
    "during", "each", "some", "other", "more", "most", "also",
    "just", "only", "very", "much", "such", "like", "over",
    "make", "made", "many", "does", "done", "being", "well",
    "back", "even", "still", "here", "take", "come", "your",
    "know", "want", "give", "find", "tell", "thing", "think",
    "good", "look", "people", "year", "way", "these", "those",
    "idea", "ideas", "essay", "startup", "experiment", "note",
    "notes", "vault", "engine", "generated", "novel", "approach",
    "system", "based", "using", "used", "work", "need", "new",
}


def extract_keywords(text: str) -> list[str]:
    """Lowercase, split on non-alpha, filter stopwords + words < 4 chars, deduplicate."""
    words = re.split(r"[^a-zA-Z]+", text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        if len(w) >= 4 and w not in STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result


# ── Models ──────────────────────────────────────────────────────


class PendingExperiment(BaseModel):
    """An experiment awaiting evaluation."""

    slug: str
    created_at: datetime
    eval_after: datetime
    idea_name: str
    hypothesis: str
    falsification_criteria: str
    experiment_path: str


class QuarantinedNote(BaseModel):
    """A note quarantined from context selection for temporal isolation."""

    path: str
    quarantined_at_run: int
    release_after_run: int


class RunRecord(BaseModel):
    """Record of a single engine run."""

    run_id: str
    timestamp: datetime
    ideas_generated: int = 0
    essays_approved: int = 0
    essays_rejected: int = 0
    startups_approved: int = 0
    startups_rejected: int = 0
    vault_hash: str = ""


class EngineState(BaseModel):
    """Full persistent state for the idea engine."""

    seen_idea_titles: set[str] = Field(default_factory=set)
    run_history: list[RunRecord] = Field(default_factory=list)
    pending_experiments: list[PendingExperiment] = Field(default_factory=list)
    vault_hash: str = ""
    last_run: datetime | None = None
    concept_frequencies: dict[str, int] = Field(default_factory=dict)
    quarantined_notes: list[QuarantinedNote] = Field(default_factory=list)
    run_count: int = 0


class StateManager:
    """Manages persistent state stored as JSON in the vault root."""

    def __init__(self, vault_path: str | Path):
        self.vault_path = Path(vault_path).expanduser()
        self.state_file = self.vault_path / ".engine-state.json"
        self.state = self.load()

    def load(self) -> EngineState:
        """Load state from file. Returns fresh state if missing or corrupt."""
        if not self.state_file.exists():
            return EngineState()

        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            # Convert set from list for JSON compatibility
            if "seen_idea_titles" in data and isinstance(
                data["seen_idea_titles"], list
            ):
                data["seen_idea_titles"] = set(data["seen_idea_titles"])
            return EngineState.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Corrupt state file, backing up and starting fresh: {e}")
            backup = self.state_file.with_suffix(".json.bak")
            shutil.copy2(self.state_file, backup)
            return EngineState()

    def save(self):
        """Atomically save state to file."""
        data = self.state.model_dump(mode="json")
        # Convert set to sorted list for JSON serialization
        data["seen_idea_titles"] = sorted(data["seen_idea_titles"])
        content = json.dumps(data, indent=2, default=str)

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_file.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.rename(self.state_file)

    def get_due_experiments(self) -> list[PendingExperiment]:
        """Return experiments whose eval_after has passed."""
        now = datetime.now()
        return [
            exp for exp in self.state.pending_experiments if exp.eval_after <= now
        ]

    def add_run_record(self, record: RunRecord):
        """Add a run record and update last_run."""
        self.state.run_history.append(record)
        self.state.last_run = record.timestamp

    def add_seen_titles(self, titles: list[str]):
        """Add titles to the seen set."""
        self.state.seen_idea_titles.update(titles)

    def add_pending_experiment(self, experiment: PendingExperiment):
        """Add a pending experiment for future evaluation."""
        self.state.pending_experiments.append(experiment)

    def remove_pending_experiment(self, slug: str):
        """Remove a pending experiment by slug."""
        self.state.pending_experiments = [
            exp for exp in self.state.pending_experiments if exp.slug != slug
        ]

    # ── Novelty Decay ───────────────────────────────────────────

    def record_concepts(self, text: str):
        """Extract keywords from text and increment frequency counts."""
        keywords = extract_keywords(text)
        for kw in keywords:
            self.state.concept_frequencies[kw] = (
                self.state.concept_frequencies.get(kw, 0) + 1
            )

    def get_overused_concepts(self, threshold: int = 3) -> dict[str, int]:
        """Return {concept: count} for concepts exceeding threshold."""
        return {
            concept: count
            for concept, count in self.state.concept_frequencies.items()
            if count > threshold
        }

    # ── Temporal Isolation ──────────────────────────────────────

    def increment_run_count(self):
        """Increment the run counter."""
        self.state.run_count += 1

    def quarantine_note(self, path: str, cycles: int):
        """Quarantine a note for the given number of run cycles."""
        self.state.quarantined_notes.append(
            QuarantinedNote(
                path=path,
                quarantined_at_run=self.state.run_count,
                release_after_run=self.state.run_count + cycles,
            )
        )

    def get_quarantined_paths(self) -> set[str]:
        """Return set of currently quarantined note paths."""
        return {q.path for q in self.state.quarantined_notes}

    def expire_quarantines(self):
        """Remove quarantined notes whose release run has passed."""
        self.state.quarantined_notes = [
            q
            for q in self.state.quarantined_notes
            if q.release_after_run > self.state.run_count
        ]
