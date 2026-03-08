"""Agent 2: Essay Judge — ruthless, independent gatekeeper."""

from typing import Any

from pydantic import BaseModel, Field

from core import load_prompt
from core.llm import CouncilResult, LLMClient


class EssayScores(BaseModel):
    """Scores for each essay evaluation dimension."""

    novelty_general: float = 0.0
    novelty_vs_vault: float = 0.0
    interest: float = 0.0
    argument_quality: float = 0.0


class EssayJudgment(BaseModel):
    """Complete judgment of an essay idea."""

    idea_title: str
    scores: EssayScores
    weighted_score: float = 0.0
    verdict: str = "reject"
    reasoning: str = ""
    suggested_vault_tags: list[str] = Field(default_factory=list)
    improvement_note: str = ""
    council_result: CouncilResult | None = None


class EssayJudgeAgent:
    """Independently judges essay ideas with optional council mode."""

    def __init__(self, llm: LLMClient, config: dict):
        self.llm = llm
        self.config = config
        self.model = config["agents"]["essay_judge_model"]
        self.system_prompt = load_prompt("essay_judge")
        self.weights = config["thresholds"]["essay_weights"]
        self.min_score = config["thresholds"]["essay_min_score"]
        self.council_enabled = config["agents"].get("essay_judge_council", False)

    def judge(self, idea: dict, vault_notes: list) -> EssayJudgment:
        """Judge an essay idea. Uses council mode if enabled."""
        # Build user message — deliberately exclude connections (blind eval)
        user_message = self._build_user_message(idea, vault_notes)

        if self.council_enabled:
            return self._judge_council(idea, user_message)
        else:
            return self._judge_single(idea, user_message)

    def _judge_single(self, idea: dict, user_message: str) -> EssayJudgment:
        raw = self.llm.call(self.system_prompt, user_message, self.model)
        return self._build_judgment(idea, raw)

    def _judge_council(self, idea: dict, user_message: str) -> EssayJudgment:
        council_models = self.config["agents"]["council_models"]
        council_result = self.llm.council_call(
            self.system_prompt, user_message, council_models
        )

        # Build judgment from council averaged scores
        scores = EssayScores(
            novelty_general=council_result.averaged_scores.get("novelty_general", 0),
            novelty_vs_vault=council_result.averaged_scores.get(
                "novelty_vs_vault", 0
            ),
            interest=council_result.averaged_scores.get("interest", 0),
            argument_quality=council_result.averaged_scores.get(
                "argument_quality", 0
            ),
        )

        weighted = self._compute_weighted_score(scores)
        verdict = "keep" if weighted >= self.min_score else "reject"

        # Collect reasoning from successful votes
        reasoning_parts = []
        for vote in council_result.votes:
            if vote.error is None:
                r = vote.parsed.get("reasoning", "")
                if r:
                    reasoning_parts.append(f"[{vote.provider}] {r}")

        # Collect tags from all votes (deduplicated, order-preserved)
        all_tags: list[str] = []
        for vote in council_result.votes:
            if vote.error is None:
                tags = vote.parsed.get("suggested_vault_tags", [])
                all_tags.extend(tags)
        unique_tags = list(dict.fromkeys(all_tags))

        # Improvement note from first successful vote
        improvement_note = ""
        for vote in council_result.votes:
            if vote.error is None:
                improvement_note = vote.parsed.get("improvement_note", "")
                if improvement_note:
                    break

        return EssayJudgment(
            idea_title=idea.get("title", ""),
            scores=scores,
            weighted_score=weighted,
            verdict=verdict,
            reasoning=" | ".join(reasoning_parts),
            suggested_vault_tags=unique_tags,
            improvement_note=improvement_note,
            council_result=council_result,
        )

    def _build_judgment(self, idea: dict, raw: dict[str, Any]) -> EssayJudgment:
        """Build judgment from raw LLM response, recomputing scores."""
        raw_scores = raw.get("scores", {})
        scores = EssayScores(
            novelty_general=float(raw_scores.get("novelty_general", 0)),
            novelty_vs_vault=float(raw_scores.get("novelty_vs_vault", 0)),
            interest=float(raw_scores.get("interest", 0)),
            argument_quality=float(raw_scores.get("argument_quality", 0)),
        )

        # Recompute — do NOT trust LLM's weighted_score
        weighted = self._compute_weighted_score(scores)
        verdict = "keep" if weighted >= self.min_score else "reject"

        return EssayJudgment(
            idea_title=idea.get("title", ""),
            scores=scores,
            weighted_score=weighted,
            verdict=verdict,
            reasoning=raw.get("reasoning", ""),
            suggested_vault_tags=raw.get("suggested_vault_tags", []),
            improvement_note=raw.get("improvement_note", ""),
        )

    def _compute_weighted_score(self, scores: EssayScores) -> float:
        """Compute weighted score from config weights."""
        return (
            scores.novelty_general * self.weights["novelty_general"]
            + scores.novelty_vs_vault * self.weights["novelty_vs_vault"]
            + scores.interest * self.weights["interest"]
            + scores.argument_quality * self.weights["argument_quality"]
        )

    def _build_user_message(self, idea: dict, vault_notes: list) -> str:
        sections = []

        sections.append("## Essay Idea to Judge\n")
        sections.append(f"**Title:** {idea.get('title', '')}")
        sections.append(f"**Hook:** {idea.get('hook', '')}")
        sections.append(
            f"**Argument sketch:** {idea.get('argument_sketch', '')}"
        )
        sections.append(f"**Novelty claim:** {idea.get('novelty_claim', '')}")
        # NOTE: connections deliberately omitted for blind evaluation

        sections.append(f"\n## Vault Context ({len(vault_notes)} notes)\n")
        for note in vault_notes:
            sections.append(f"### {note.title}")
            sections.append(note.preview)
            sections.append("---")

        return "\n".join(sections)
