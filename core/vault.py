"""Obsidian vault reader/writer with atomic operations."""

import hashlib
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter
from pydantic import BaseModel, Field


class VaultNote(BaseModel):
    """A single note from the Obsidian vault."""

    title: str
    path: Path
    content: str
    preview: str = ""
    tags: list[str] = Field(default_factory=list)
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    modified_at: datetime
    word_count: int = 0

    model_config = {"arbitrary_types_allowed": True}


class VaultManager:
    """Reads and writes Obsidian vault notes with atomic operations."""

    def __init__(self, config: dict):
        self.vault_path = Path(config["vault"]["path"]).expanduser()
        self.idea_engine_folder = config["vault"]["idea_engine_folder"]
        self.scan_glob = config["vault"]["scan_glob"]
        self.exclude_folders = config["vault"].get("exclude_folders", [])

    def scan_notes(self) -> list[VaultNote]:
        """Walk vault with glob, parse frontmatter, exclude configured folders."""
        notes = []
        for md_path in self.vault_path.glob(self.scan_glob):
            rel = md_path.relative_to(self.vault_path)
            # Skip excluded folders
            if rel.parts and any(rel.parts[0] == exc for exc in self.exclude_folders):
                continue
            # Skip hidden files/dirs
            if any(part.startswith(".") for part in rel.parts):
                continue

            try:
                post = frontmatter.load(str(md_path))
                content = post.content
                fm = dict(post.metadata)
            except Exception:
                content = md_path.read_text(encoding="utf-8", errors="replace")
                fm = {}

            # Extract title from first H1 or filename
            title = md_path.stem
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            tags = fm.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]

            stat = md_path.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime)

            notes.append(
                VaultNote(
                    title=title,
                    path=md_path,
                    content=content,
                    preview=content[:200],
                    tags=tags,
                    frontmatter=fm,
                    modified_at=modified_at,
                    word_count=len(content.split()),
                )
            )
        return notes

    def select_context_notes(
        self, n: int, strategy: str = "recent_and_random"
    ) -> list[VaultNote]:
        """Select n context notes using the specified strategy."""
        all_notes = self.scan_notes()
        if not all_notes:
            return []
        n = min(n, len(all_notes))

        if strategy == "recent_and_random":
            sorted_notes = sorted(
                all_notes, key=lambda x: x.modified_at, reverse=True
            )
            recent_count = n // 2
            recent = sorted_notes[:recent_count]
            remaining = [note for note in all_notes if note not in recent]
            random_count = n - recent_count
            random_picks = random.sample(remaining, min(random_count, len(remaining)))
            return recent + random_picks
        elif strategy == "recent":
            sorted_notes = sorted(
                all_notes, key=lambda x: x.modified_at, reverse=True
            )
            return sorted_notes[:n]
        elif strategy == "random":
            return random.sample(all_notes, n)
        else:
            return all_notes[:n]

    def _ensure_dirs(self):
        """Ensure idea engine directories exist."""
        base = self.vault_path / self.idea_engine_folder
        (base / "essays").mkdir(parents=True, exist_ok=True)
        (base / "startups").mkdir(parents=True, exist_ok=True)
        (base / "rejected").mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, path: Path, content: str):
        """Write content atomically: write to .tmp then rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.rename(path)

    def write_essay_idea(self, idea: dict, judgment: dict, run_id: str) -> Path:
        """Write an approved essay idea to the vault."""
        self._ensure_dirs()
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = self._slugify(idea["title"])
        filename = f"{date_str}-{slug}.md"
        path = self.vault_path / self.idea_engine_folder / "essays" / filename

        tags = ["essay-idea", "engine-generated"]
        if judgment.get("suggested_vault_tags"):
            tags.extend(judgment["suggested_vault_tags"])

        connections = idea.get("connections", [])

        content = f"""---
tags: [{", ".join(tags)}]
date: {date_str}
score: {judgment.get("weighted_score", 0):.2f}
connections: [{", ".join(connections)}]
engine_run_id: "{run_id}"
---

# {idea["title"]}

**Hook:** {idea.get("hook", "")}

**Argument:** {idea.get("argument_sketch", "")}

**Novelty claim:** {idea.get("novelty_claim", "")}

**Judge reasoning:** {judgment.get("reasoning", "")}

**Improvement note:** {judgment.get("improvement_note", "None")}
"""
        self._atomic_write(path, content)
        return path

    def write_startup_judgment(
        self, idea: dict, judgment: dict, run_id: str
    ) -> Path:
        """Write a startup judgment to the vault."""
        self._ensure_dirs()
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = self._slugify(idea["name"])
        filename = f"{date_str}-{slug}.md"
        path = self.vault_path / self.idea_engine_folder / "startups" / filename

        content = f"""---
tags: [startup-idea, engine-generated]
date: {date_str}
score: {judgment.get("weighted_score", 0):.2f}
verdict: {judgment.get("verdict", "unknown")}
engine_run_id: "{run_id}"
---

# {idea["name"]}

**Problem:** {idea.get("problem", "")}

**Insight:** {idea.get("insight", "")}

**Target user:** {idea.get("target_user", "")}

**Core mechanic:** {idea.get("core_mechanic", "")}

**Hypothesis:** {idea.get("experiment_hypothesis", "")}

**Judge reasoning:** {judgment.get("reasoning", "")}

**Scores:**
- Problem acuity: {judgment.get("scores", {}).get("problem_acuity", "N/A")}
- Insight non-obviousness: {judgment.get("scores", {}).get("insight_non_obviousness", "N/A")}
- Experiment tractability: {judgment.get("scores", {}).get("experiment_tractability", "N/A")}
- Market signal: {judgment.get("scores", {}).get("market_signal", "N/A")}
"""
        self._atomic_write(path, content)
        return path

    def write_rejection(self, item: dict, category: str, run_id: str) -> Path:
        """Write a rejection note to the vault."""
        self._ensure_dirs()
        date_str = datetime.now().strftime("%Y-%m-%d")
        name = item.get("title", item.get("name", "unknown"))
        slug = self._slugify(name)
        filename = f"{date_str}-rejected-{slug}.md"
        path = self.vault_path / self.idea_engine_folder / "rejected" / filename

        content = f"""---
tags: [rejected, {category}]
date: {date_str}
score: {item.get("weighted_score", 0):.2f}
engine_run_id: "{run_id}"
---

# [Rejected] {name}

**Reasoning:** {item.get("reasoning", "No reasoning provided")}

**Improvement note:** {item.get("improvement_note", "None")}
"""
        self._atomic_write(path, content)
        return path

    def write_experiment_result(self, result: dict, run_id: str) -> Path:
        """Write an experiment evaluation result to the vault."""
        self._ensure_dirs()
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = self._slugify(result.get("experiment_slug", "unknown"))
        filename = f"{date_str}-experiment-{slug}.md"
        path = self.vault_path / self.idea_engine_folder / "startups" / filename

        content = f"""---
tags: [experiment-result, engine-generated]
date: {date_str}
score: {result.get("score", 0):.2f}
verdict: {result.get("hypothesis_verdict", "unknown")}
recommendation: {result.get("recommendation", "unknown")}
engine_run_id: "{run_id}"
---

# Experiment Result: {result.get("experiment_slug", "unknown")}

**Hypothesis verdict:** {result.get("hypothesis_verdict", "")}

**Score:** {result.get("score", "N/A")}

**Evidence:** {result.get("evidence", "")}

**Recommendation:** {result.get("recommendation", "")}

**Iteration suggestion:** {result.get("iteration_suggestion", "None")}
"""
        self._atomic_write(path, content)
        return path

    def compute_content_hash(self) -> str:
        """SHA256 of sorted note filenames + mtimes."""
        entries = []
        for md_path in sorted(self.vault_path.glob(self.scan_glob)):
            rel = md_path.relative_to(self.vault_path)
            if rel.parts and any(
                rel.parts[0] == exc for exc in self.exclude_folders
            ):
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            stat = md_path.stat()
            entries.append(f"{rel}:{stat.st_mtime}")
        hash_input = "\n".join(entries)
        return hashlib.sha256(hash_input.encode()).hexdigest()

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to a URL-friendly slug."""
        slug = text.lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug[:40]
