"""Experiment scaffolder for startup ideas."""

import json
import re
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ExperimentFile(BaseModel):
    """A single file to be written in the experiment scaffold."""

    filename: str
    content: str


class ExperimentScaffold(BaseModel):
    """Full scaffold specification for an experiment."""

    experiment_type: Literal[
        "cli_script", "html_prototype", "api_stub", "data_analysis", "llm_pipeline"
    ]
    slug: str
    readme_content: str
    eval_criteria_content: str
    implementation_files: list[ExperimentFile] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ExperimentScaffolder:
    """Creates, reads, and promotes experiment folders."""

    def __init__(self, config: dict):
        self.experiments_path = Path(config["dev"]["experiments_path"]).expanduser()
        self.approved_path = Path(config["dev"]["approved_path"]).expanduser()

    @staticmethod
    def make_slug(name: str) -> str:
        """Convert name to a filesystem-safe slug."""
        slug = name.lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug[:40]

    def create_experiment(self, scaffold: ExperimentScaffold, meta: dict) -> Path:
        """Create experiment folder with all scaffolded files."""
        exp_dir = self.experiments_path / scaffold.slug
        src_dir = exp_dir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        # pyproject.toml
        (exp_dir / "pyproject.toml").write_text(
            self._build_pyproject_toml(scaffold), encoding="utf-8"
        )

        # README.md
        (exp_dir / "README.md").write_text(
            scaffold.readme_content, encoding="utf-8"
        )

        # EVAL_CRITERIA.md
        (exp_dir / "EVAL_CRITERIA.md").write_text(
            scaffold.eval_criteria_content, encoding="utf-8"
        )

        # .engine-meta.json
        (exp_dir / ".engine-meta.json").write_text(
            json.dumps(meta, indent=2, default=str), encoding="utf-8"
        )

        # Implementation files
        for impl_file in scaffold.implementation_files:
            file_path = src_dir / impl_file.filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(impl_file.content, encoding="utf-8")

        return exp_dir

    @staticmethod
    def _build_pyproject_toml(scaffold: ExperimentScaffold) -> str:
        """Generate a pyproject.toml for the experiment."""
        deps = scaffold.dependencies or []
        deps_str = ", ".join(f'"{d}"' for d in deps)
        return (
            f'[project]\n'
            f'name = "{scaffold.slug}"\n'
            f'version = "0.1.0"\n'
            f'requires-python = ">=3.11"\n'
            f'dependencies = [{deps_str}]\n'
        )

    def read_experiment(self, slug: str) -> dict:
        """Read experiment files for evaluation."""
        exp_dir = self.experiments_path / slug
        if not exp_dir.exists():
            raise FileNotFoundError(f"Experiment not found: {exp_dir}")

        result = {"slug": slug, "files": {}}

        # Read known files
        for name in ["pyproject.toml", "README.md", "EVAL_CRITERIA.md", ".engine-meta.json"]:
            fpath = exp_dir / name
            if fpath.exists():
                result["files"][name] = fpath.read_text(encoding="utf-8")

        # Read src/ files
        src_dir = exp_dir / "src"
        if src_dir.exists():
            for src_file in src_dir.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(exp_dir)
                    try:
                        result["files"][str(rel)] = src_file.read_text(
                            encoding="utf-8"
                        )
                    except UnicodeDecodeError:
                        result["files"][str(rel)] = "<binary file>"

        return result

    def promote_experiment(self, slug: str) -> Path:
        """Move experiment from experiments/ to projects/."""
        src = self.experiments_path / slug
        dst = self.approved_path / slug

        if not src.exists():
            raise FileNotFoundError(f"Experiment not found: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return dst
