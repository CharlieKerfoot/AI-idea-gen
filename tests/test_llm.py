"""Tests for core/llm.py — JSON extraction, council mode, retry."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.llm import CouncilVote, LLMClient, extract_json


# ── JSON Extraction Tests ────────────────────────────────────────


def test_extract_json_from_code_fence():
    """Should extract JSON from a ```json code fence."""
    text = """Here's the result:

```json
{
  "title": "Test Idea",
  "score": 7.5
}
```

That's my analysis."""

    result = extract_json(text)
    assert result["title"] == "Test Idea"
    assert result["score"] == 7.5


def test_extract_json_raw_fallback():
    """Should parse raw JSON when no code fence is present."""
    text = '{"title": "Raw JSON", "score": 8.0}'

    result = extract_json(text)
    assert result["title"] == "Raw JSON"
    assert result["score"] == 8.0


def test_extract_json_balanced_brace():
    """Should find JSON via balanced-brace search as last resort."""
    text = 'Some preamble text {"title": "Found It", "nested": {"key": "val"}} trailing'

    result = extract_json(text)
    assert result["title"] == "Found It"
    assert result["nested"]["key"] == "val"


def test_extract_json_failure():
    """Should raise ValueError when no JSON can be extracted."""
    with pytest.raises(ValueError, match="Could not extract JSON"):
        extract_json("No JSON here at all, just plain text.")


# ── Helper to build a mock LLMClient ─────────────────────────────


def _make_mock_client(mock_response: str | dict | None = None) -> LLMClient:
    """Create an LLMClient with a mocked anthropic provider."""
    config = {"agents": {"generator_model": "claude-opus-4-6"}}

    with patch.object(LLMClient, "_init_providers"):
        client = LLMClient(config)

    mock_provider = MagicMock()
    if mock_response is not None:
        if isinstance(mock_response, dict):
            mock_provider.call.return_value = json.dumps(mock_response)
        else:
            mock_provider.call.return_value = mock_response
    client.providers = {"anthropic": mock_provider}

    return client


# ── Council Mode Tests ───────────────────────────────────────────


def test_council_skips_unavailable_provider():
    """Council should skip providers whose keys are not set."""
    client = _make_mock_client(
        {"scores": {"novelty_general": 7.0, "interest": 6.0}, "verdict": "keep", "reasoning": "Good idea"}
    )

    council_models = [
        {"provider": "anthropic", "model": "claude-opus-4-6"},
        {"provider": "openai", "model": "gpt-4o"},  # Not in client.providers
    ]

    result = client.council_call("system", "user", council_models)

    assert "openai" in result.providers_skipped
    assert len([v for v in result.votes if v.error is None]) == 1


def test_council_majority_verdict():
    """Council verdict should be determined by majority."""
    client = _make_mock_client(
        {"scores": {"novelty_general": 8.0, "interest": 7.0}, "verdict": "keep", "reasoning": "Solid idea"}
    )

    result = client.council_call(
        "system",
        "user",
        [{"provider": "anthropic", "model": "claude-opus-4-6"}],
    )

    assert result.final_verdict == "keep"
    assert result.consensus_level == 1.0
    assert result.averaged_scores["novelty_general"] == 8.0


# ── Client Call Test ─────────────────────────────────────────────


def test_client_call_extracts_json():
    """LLMClient.call should extract JSON from provider response."""
    client = _make_mock_client('```json\n{"result": "success"}\n```')

    result = client.call("system prompt", "user message")
    assert result["result"] == "success"
