"""LLM client abstraction with multi-provider support and council mode."""

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)


# ── Models ───────────────────────────────────────────────────────


class CouncilVote(BaseModel):
    """A single provider's vote in council mode."""

    provider: str
    model: str
    raw_response: str = ""
    parsed: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class CouncilResult(BaseModel):
    """Aggregated result from a council vote."""

    votes: list[CouncilVote] = Field(default_factory=list)
    averaged_scores: dict[str, float] = Field(default_factory=dict)
    final_verdict: str = ""
    consensus_level: float = 0.0
    dissenting_reasoning: list[str] = Field(default_factory=list)
    providers_skipped: list[str] = Field(default_factory=list)


# ── Providers ────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def call(self, system_prompt: str, user_message: str, model: str) -> str:
        """Make an LLM call and return the text response."""
        ...


class AnthropicProvider(LLMProvider):
    def __init__(self):
        import anthropic

        self.client = anthropic.Anthropic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=4, max=10),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=lambda retry_state: logger.warning(
            f"Anthropic retry attempt {retry_state.attempt_number}"
        ),
    )
    def call(self, system_prompt: str, user_message: str, model: str) -> str:
        message = self.client.messages.create(
            model=model,
            max_tokens=16384,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return message.content[0].text


class OpenAIProvider(LLMProvider):
    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=4, max=10),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=lambda retry_state: logger.warning(
            f"OpenAI retry attempt {retry_state.attempt_number}"
        ),
    )
    def call(self, system_prompt: str, user_message: str, model: str) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=16384,
        )
        return response.choices[0].message.content


class GoogleProvider(LLMProvider):
    def __init__(self):
        import google.generativeai as genai

        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        self.genai = genai

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=4, max=10),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=lambda retry_state: logger.warning(
            f"Google retry attempt {retry_state.attempt_number}"
        ),
    )
    def call(self, system_prompt: str, user_message: str, model: str) -> str:
        gmodel = self.genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
        )
        response = gmodel.generate_content(user_message)
        return response.text


# ── Provider Registry ────────────────────────────────────────────

PROVIDER_REGISTRY: dict[str, tuple[type[LLMProvider], str]] = {
    "anthropic": (AnthropicProvider, "ANTHROPIC_API_KEY"),
    "openai": (OpenAIProvider, "OPENAI_API_KEY"),
    "google": (GoogleProvider, "GOOGLE_API_KEY"),
}


# ── JSON Extraction ──────────────────────────────────────────────


def extract_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response using 3-tier strategy.

    1. Extract from ```json ``` code fence
    2. Parse entire response as raw JSON
    3. Balanced-brace finder for JSON embedded in text
    """
    # Tier 1: code fence — find ```json, then use balanced-brace extraction
    # from that point (handles embedded ``` inside JSON string values)
    fence_start = text.find("```json")
    if fence_start != -1:
        json_region = text[fence_start + len("```json"):]
        try:
            return _extract_braced_json(json_region)
        except ValueError:
            pass

    # Tier 2: raw JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Tier 3: balanced-brace finder on full text
    try:
        return _extract_braced_json(text)
    except ValueError:
        pass

    raise ValueError(f"Could not extract JSON from response: {text[:200]}...")


def _extract_braced_json(text: str) -> dict[str, Any]:
    """Find the first valid JSON object using string-aware brace matching."""
    start = text.find("{")
    if start == -1:
        raise ValueError("No opening brace found")

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue

        if ch == "\\":
            if in_string:
                escape = True
            continue

        if ch == '"' and not escape:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    raise ValueError("Matched braces but invalid JSON")

    raise ValueError("No balanced JSON object found")


# ── LLM Client ───────────────────────────────────────────────────


class LLMClient:
    """Multi-provider LLM client with council mode support."""

    def __init__(self, config: dict):
        self.config = config
        self.providers: dict[str, LLMProvider] = {}
        self._init_providers()

    def _init_providers(self):
        """Initialize providers whose API keys are available."""
        for name, (provider_cls, env_key) in PROVIDER_REGISTRY.items():
            if os.environ.get(env_key):
                try:
                    self.providers[name] = provider_cls()
                    logger.info(f"Initialized {name} provider")
                except Exception as e:
                    logger.warning(f"Failed to initialize {name}: {e}")

        if "anthropic" not in self.providers:
            raise RuntimeError(
                "Anthropic provider is required. Set ANTHROPIC_API_KEY."
            )

    def call(
        self, system_prompt: str, user_message: str, model: str | None = None
    ) -> dict[str, Any]:
        """Make an LLM call and extract structured JSON response."""
        if model is None:
            model = self.config["agents"]["generator_model"]

        provider = self.providers["anthropic"]
        raw = provider.call(system_prompt, user_message, model)
        return extract_json(raw)

    def council_call(
        self,
        system_prompt: str,
        user_message: str,
        council_models: list[dict],
    ) -> CouncilResult:
        """Dispatch to multiple providers and aggregate results."""
        result = CouncilResult()

        def _call_provider(council_entry: dict) -> CouncilVote:
            provider_name = council_entry["provider"]
            model = council_entry["model"]

            if provider_name not in self.providers:
                result.providers_skipped.append(provider_name)
                return CouncilVote(
                    provider=provider_name,
                    model=model,
                    error=f"Provider {provider_name} not available",
                )

            try:
                raw = self.providers[provider_name].call(
                    system_prompt, user_message, model
                )
                parsed = extract_json(raw)
                return CouncilVote(
                    provider=provider_name,
                    model=model,
                    raw_response=raw,
                    parsed=parsed,
                )
            except Exception as e:
                logger.error(f"Council call to {provider_name} failed: {e}")
                return CouncilVote(
                    provider=provider_name,
                    model=model,
                    error=str(e),
                )

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_call_provider, entry): entry
                for entry in council_models
            }
            for future in as_completed(futures):
                vote = future.result()
                result.votes.append(vote)

        # Aggregate successful votes
        successful = [v for v in result.votes if v.error is None]
        if not successful:
            raise RuntimeError("All council providers failed")

        # Average scores
        all_score_keys: set[str] = set()
        for vote in successful:
            scores = vote.parsed.get("scores", {})
            all_score_keys.update(scores.keys())

        for key in all_score_keys:
            values = []
            for vote in successful:
                val = vote.parsed.get("scores", {}).get(key)
                if val is not None:
                    values.append(float(val))
            if values:
                result.averaged_scores[key] = sum(values) / len(values)

        # Majority verdict
        verdicts = [v.parsed.get("verdict", "") for v in successful]
        verdict_counts: dict[str, int] = {}
        for v in verdicts:
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
        result.final_verdict = max(verdict_counts, key=verdict_counts.get)

        # Consensus level
        majority_count = verdict_counts[result.final_verdict]
        result.consensus_level = majority_count / len(successful)

        # Dissenting reasoning
        for vote in successful:
            if vote.parsed.get("verdict") != result.final_verdict:
                reasoning = vote.parsed.get("reasoning", "")
                if reasoning:
                    result.dissenting_reasoning.append(
                        f"[{vote.provider}] {reasoning}"
                    )

        # Track skipped providers from errors
        for vote in result.votes:
            if vote.error and vote.provider not in result.providers_skipped:
                result.providers_skipped.append(vote.provider)

        return result
