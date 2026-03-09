"""Agent 1: Idea Generator — maximally creative, no self-censorship."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core import load_prompt
from core.entropy import EntropyConcept
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
        entropy_concept: EntropyConcept | None = None,
        overused_concepts: list[str] | None = None,
    ) -> GeneratorOutput:
        """Generate essay and startup ideas from vault context."""
        user_message = self._build_user_message(
            vault_notes, seen_titles, n_ideas, entropy_concept, overused_concepts
        )
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
        self,
        vault_notes: list,
        seen_titles: set[str],
        n_ideas: int,
        entropy_concept: EntropyConcept | None = None,
        overused_concepts: list[str] | None = None,
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

        # Entropy injection
        if entropy_concept:
            sections.append("\n## External Stimulus (MUST integrate)")
            sections.append(f"**Concept:** {entropy_concept.title} (from {entropy_concept.domain})")
            sections.append(f"**Summary:** {entropy_concept.summary}")
            sections.append(
                "At least one of your generated ideas MUST meaningfully engage with this concept."
            )
            sections.append(
                "Do not mention it superficially — use it as a core ingredient "
                "in the idea's argument or mechanism."
            )

        # Overused concepts
        if overused_concepts:
            sections.append("\n## Overused Concepts (AVOID)")
            sections.append(
                "The following concepts have appeared too frequently in previous runs. "
                "Actively steer away:"
            )
            for concept in overused_concepts:
                sections.append(f"- {concept}")

        # Task
        sections.append(f"\n## Task\n")
        sections.append(
            f"Generate {n_ideas} essay ideas and {n_ideas} startup ideas."
        )

        return "\n".join(sections)
