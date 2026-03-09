"""Agent 3: Startup Judge + Experiment Builder — three modes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from core import load_prompt
from core.experiment import ExperimentFile, ExperimentScaffold, ExperimentScaffolder
from core.llm import LLMClient
from core.state import PendingExperiment, extract_keywords


class StartupScores(BaseModel):
    """Scores for each startup evaluation dimension."""

    problem_acuity: float = 0.0
    insight_non_obviousness: float = 0.0
    experiment_tractability: float = 0.0
    market_signal: float = 0.0


class StartupJudgment(BaseModel):
    """Complete viability judgment of a startup idea."""

    idea_name: str
    scores: StartupScores
    weighted_score: float = 0.0
    verdict: str = "reject"
    reasoning: str = ""


class ExperimentResult(BaseModel):
    """Result of evaluating a scaffolded experiment."""

    experiment_slug: str
    hypothesis_verdict: Literal["validated", "falsified", "inconclusive"] = (
        "inconclusive"
    )
    score: float = 0.0
    evidence: str = ""
    recommendation: Literal["promote", "scrap", "iterate"] = "scrap"
    iteration_suggestion: str = ""


class StartupJudgeAgent:
    """Evaluates startup ideas, scaffolds experiments, evaluates results."""

    def __init__(
        self,
        llm: LLMClient,
        config: dict,
        scaffolder: ExperimentScaffolder,
    ):
        self.llm = llm
        self.config = config
        self.model = config["agents"]["startup_judge_model"]
        self.eval_model = config["agents"]["experiment_eval_model"]
        self.system_prompt = load_prompt("startup_judge")
        self.eval_prompt = load_prompt("experiment_eval")
        self.weights = config["thresholds"]["startup_weights"]
        self.min_viability = config["thresholds"]["startup_min_viability"]
        self.scaffolder = scaffolder
        self.novelty_decay_penalty = config["thresholds"].get(
            "novelty_decay_penalty", 0.3
        )
        self.novelty_decay_threshold = config["thresholds"].get(
            "novelty_decay_threshold", 3
        )

    # ── Mode A: Viability Judge ──────────────────────────────────

    def judge_viability(
        self,
        idea: dict,
        overused_concepts: dict[str, int] | None = None,
    ) -> StartupJudgment:
        """Score a startup idea for viability."""
        user_message = self._build_mode_a_message(idea)
        raw = self.llm.call(self.system_prompt, user_message, self.model)

        raw_scores = raw.get("scores", {})
        scores = StartupScores(
            problem_acuity=float(raw_scores.get("problem_acuity", 0)),
            insight_non_obviousness=float(
                raw_scores.get("insight_non_obviousness", 0)
            ),
            experiment_tractability=float(
                raw_scores.get("experiment_tractability", 0)
            ),
            market_signal=float(raw_scores.get("market_signal", 0)),
        )

        weighted = self._compute_weighted_score(scores)
        verdict = "viable" if weighted >= self.min_viability else "reject"

        judgment = StartupJudgment(
            idea_name=idea.get("name", ""),
            scores=scores,
            weighted_score=weighted,
            verdict=verdict,
            reasoning=raw.get("reasoning", ""),
        )

        if overused_concepts:
            judgment = self._apply_novelty_decay(judgment, idea, overused_concepts)

        return judgment

    # ── Mode B: Experiment Scaffolder ────────────────────────────

    def scaffold_experiment(self, idea: dict) -> PendingExperiment:
        """Design and scaffold a minimal experiment for a viable idea."""
        user_message = self._build_mode_b_message(idea)
        raw = self.llm.call(self.system_prompt, user_message, self.model)

        # Build scaffold from LLM output
        impl_files = [
            ExperimentFile(filename=f["filename"], content=f["content"])
            for f in raw.get("implementation_files", [])
        ]

        slug = self.scaffolder.make_slug(idea.get("name", "experiment"))
        experiment_type = raw.get("experiment_type", "cli_script")
        scaffold = ExperimentScaffold(
            experiment_type=experiment_type,
            slug=slug,
            readme_content=raw.get("readme_content", ""),
            eval_criteria_content=raw.get("eval_criteria_content", ""),
            implementation_files=impl_files,
            dependencies=raw.get("dependencies", []),
        )
        now = datetime.now()
        pending = PendingExperiment(
            slug=slug,
            created_at=now,
            eval_after=now + timedelta(hours=24),
            idea_name=idea.get("name", ""),
            hypothesis=idea.get("experiment_hypothesis", ""),
            falsification_criteria=idea.get("falsification_criteria", ""),
            experiment_path=str(self.scaffolder.experiments_path / slug),
            experiment_type=experiment_type,
        )

        meta = pending.model_dump(mode="json")
        self.scaffolder.create_experiment(scaffold, meta)

        return pending

    # ── Mode C: Experiment Evaluator ─────────────────────────────

    def evaluate_experiment(self, pending: PendingExperiment) -> ExperimentResult:
        """Evaluate an experiment with a fresh, unbiased LLM call."""
        try:
            exp_data = self.scaffolder.read_experiment(pending.slug)
        except FileNotFoundError:
            return ExperimentResult(
                experiment_slug=pending.slug,
                hypothesis_verdict="inconclusive",
                score=0.0,
                evidence="Experiment folder not found",
                recommendation="scrap",
            )

        user_message = self._build_mode_c_message(pending, exp_data)
        raw = self.llm.call(self.eval_prompt, user_message, self.eval_model)

        return ExperimentResult(
            experiment_slug=pending.slug,
            hypothesis_verdict=raw.get("hypothesis_verdict", "inconclusive"),
            score=float(raw.get("score", 0)),
            evidence=raw.get("evidence", ""),
            recommendation=raw.get("recommendation", "scrap"),
            iteration_suggestion=raw.get("iteration_suggestion", ""),
        )

    # ── Private helpers ──────────────────────────────────────────

    def _apply_novelty_decay(
        self,
        judgment: StartupJudgment,
        idea: dict,
        overused_concepts: dict[str, int],
    ) -> StartupJudgment:
        """Penalize insight_non_obviousness for ideas reusing overused concepts."""
        idea_text = " ".join(
            [
                idea.get("name", ""),
                idea.get("problem", ""),
                idea.get("insight", ""),
            ]
        )
        idea_keywords = set(extract_keywords(idea_text))

        total_penalty = 0.0
        for concept, count in overused_concepts.items():
            if concept in idea_keywords:
                total_penalty += self.novelty_decay_penalty * (
                    count - self.novelty_decay_threshold
                )

        if total_penalty > 0:
            new_score = max(
                0.0, judgment.scores.insight_non_obviousness - total_penalty
            )
            judgment.scores.insight_non_obviousness = new_score
            judgment.weighted_score = self._compute_weighted_score(judgment.scores)
            judgment.verdict = (
                "viable"
                if judgment.weighted_score >= self.min_viability
                else "reject"
            )

        return judgment

    def _compute_weighted_score(self, scores: StartupScores) -> float:
        """Compute weighted score from config weights."""
        return (
            scores.problem_acuity * self.weights["problem_acuity"]
            + scores.insight_non_obviousness
            * self.weights["insight_non_obviousness"]
            + scores.experiment_tractability
            * self.weights["experiment_tractability"]
            + scores.market_signal * self.weights["market_signal"]
        )

    def _build_mode_a_message(self, idea: dict) -> str:
        return f"""## Mode: Viability Assessment

## Startup Idea

**Name:** {idea.get("name", "")}
**Problem:** {idea.get("problem", "")}
**Insight:** {idea.get("insight", "")}
**Target user:** {idea.get("target_user", "")}
**Core mechanic:** {idea.get("core_mechanic", "")}
**Hypothesis:** {idea.get("experiment_hypothesis", "")}
**Falsification criteria:** {idea.get("falsification_criteria", "")}

Score this idea on the four dimensions and provide your verdict."""

    def _build_mode_b_message(self, idea: dict) -> str:
        return f"""## Mode: Experiment Design

## Startup Idea

**Name:** {idea.get("name", "")}
**Problem:** {idea.get("problem", "")}
**Insight:** {idea.get("insight", "")}
**Target user:** {idea.get("target_user", "")}
**Core mechanic:** {idea.get("core_mechanic", "")}
**Hypothesis:** {idea.get("experiment_hypothesis", "")}
**Falsification criteria:** {idea.get("falsification_criteria", "")}

Design the simplest possible experiment to test ONLY the core mechanic."""

    def _build_mode_c_message(
        self, pending: PendingExperiment, exp_data: dict
    ) -> str:
        sections = [
            "## Experiment Evaluation\n",
            f"**Experiment slug:** {pending.slug}",
            f"**Hypothesis:** {pending.hypothesis}",
            f"**Falsification criteria:** {pending.falsification_criteria}\n",
        ]

        for filename, content in exp_data.get("files", {}).items():
            sections.append(f"### File: {filename}")
            sections.append(f"```\n{content}\n```\n")

        return "\n".join(sections)
