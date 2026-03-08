"""Core utilities for the Obsidian Idea Engine."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def load_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    prompt_path = PROJECT_ROOT / "prompts" / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
