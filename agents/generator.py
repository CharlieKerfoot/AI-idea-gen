"""Agent 1: Idea Generator — maximally creative, no self-censorship."""

from pydantic import BaseModel, Field

from core import load_prompt
from core.llm import LLMClient


class EssayIdea(BaseModel):
    """A generated essay idea."""

    title: str
    hook: str
    argument_sketch: str
    connections: list[str] = Field(default_factory=list)
    novelty_claim: str


class StartupIdea(BaseModel):
    """A generated startup idea."""

    name: str
    problem: str
    insight: str
    target_user: str
    core_mechanic: str
    experiment_hypothesis: str
    falsification_criteria: str


class GeneratorOutput(BaseModel):
    """Combined output from the generator agent."""

    essay_ideas: list[EssayIdea] = Field(default_factory=list)
    startup_ideas: list[StartupIdea] = Field(default_factory=list)


class GeneratorAgent:
    """Generates essay and startup ideas from vault context."""

    def __init__(self, llm: LLMClient, config: dict):
        self.llm = llm
        self.config = config
        self.model = config["agents"]["generator_model"]
        self.system_prompt = load_prompt("generator")

    def generate(
        self,
        vault_notes: list,
        seen_titles: set[str],
        n_ideas: int,
    ) -> GeneratorOutput:
        """Generate essay and startup ideas from vault context."""
        user_message = self._build_user_message(vault_notes, seen_titles, n_ideas)
        raw = self.llm.call(self.system_prompt, user_message, self.model)

        output = GeneratorOutput.model_validate(raw)

        # Filter out any ideas whose titles match seen titles
        seen_lower = {t.lower() for t in seen_titles}
        output.essay_ideas = [
            idea
            for idea in output.essay_ideas
            if idea.title.lower() not in seen_lower
        ]
        output.startup_ideas = [
            idea
            for idea in output.startup_ideas
            if idea.name.lower() not in seen_lower
        ]

        return output

    def _build_user_message(
        self, vault_notes: list, seen_titles: set[str], n_ideas: int
    ) -> str:
        sections = []

        # Vault context
        sections.append(f"## Vault Context ({len(vault_notes)} notes)\n")
        for note in vault_notes:
            sections.append(f"### {note.title}")
            sections.append(note.preview)
            sections.append("---")

        # Previously generated titles
        if seen_titles:
            sections.append("\n## Previously Generated Ideas (do not repeat)\n")
            for title in sorted(seen_titles):
                sections.append(f"- {title}")

        # Task
        sections.append(f"\n## Task\n")
        sections.append(
            f"Generate {n_ideas} essay ideas and {n_ideas} startup ideas."
        )

        return "\n".join(sections)
