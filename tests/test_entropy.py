"""Tests for core/entropy.py — entropy injection strategies."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.entropy import (
    ADJACENT_DOMAIN_POOLS,
    CURATED_DOMAIN_POOLS,
    DEFAULT_ARXIV_SCHEDULE,
    EntropyConcept,
    _detect_vault_density,
    _strategy_adjacent_possible,
    _strategy_arxiv_rotation,
    _strategy_curated_random,
    fetch_entropy_concept,
)


@pytest.fixture
def base_config():
    return {
        "entropy": {
            "enabled": True,
            "strategy": "curated_random",
            "curated_random": {
                "domains": ["mathematics", "linguistics"],
            },
            "arxiv_rotation": {
                "schedule": {0: "math", 1: "q-bio", 2: "cs.AI"},
                "max_results": 3,
            },
            "adjacent_possible": {
                "fallback_domain": "mathematics",
            },
        }
    }


def _make_wiki_response(title="Test Article", extract="Sentence one. Sentence two. Sentence three."):
    """Create a mock Wikipedia API response."""
    return json.dumps({
        "title": title,
        "extract": extract,
        "content_urls": {
            "desktop": {"page": f"https://en.wikipedia.org/wiki/{title}"}
        },
    }).encode("utf-8")


def _make_arxiv_response(title="Test Paper", summary="An interesting paper. About something. Really."):
    """Create a mock arXiv Atom XML response."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>{title}</title>
    <summary>{summary}</summary>
    <id>http://arxiv.org/abs/2024.12345</id>
    <link href="http://arxiv.org/abs/2024.12345" type="text/html"/>
  </entry>
</feed>""".encode("utf-8")


class TestCuratedDomainPools:
    def test_all_domains_have_pools(self):
        """Every domain key should have at least 10 articles."""
        for domain, articles in CURATED_DOMAIN_POOLS.items():
            assert len(articles) >= 10, f"{domain} has only {len(articles)} articles"

    def test_no_empty_article_titles(self):
        for domain, articles in CURATED_DOMAIN_POOLS.items():
            for article in articles:
                assert article.strip(), f"Empty article in {domain}"


class TestCuratedRandomStrategy:
    @patch("core.entropy.urlopen")
    def test_returns_concept_on_success(self, mock_urlopen, base_config):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_wiki_response("Topology")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _strategy_curated_random(base_config)

        assert result is not None
        assert isinstance(result, EntropyConcept)
        assert result.source == "wikipedia"
        assert result.strategy == "curated_random"
        assert result.domain in ["mathematics", "linguistics"]

    @patch("core.entropy.urlopen", side_effect=TimeoutError("timeout"))
    def test_returns_none_on_failure(self, mock_urlopen, base_config):
        result = _strategy_curated_random(base_config)
        assert result is None

    def test_invalid_domains_filtered(self):
        config = {
            "entropy": {
                "curated_random": {"domains": ["nonexistent_domain"]},
            }
        }
        result = _strategy_curated_random(config)
        assert result is None


class TestArxivRotationStrategy:
    @patch("core.entropy.urlopen")
    def test_returns_concept_on_success(self, mock_urlopen, base_config):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_arxiv_response()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _strategy_arxiv_rotation(base_config)

        assert result is not None
        assert isinstance(result, EntropyConcept)
        assert result.source == "arxiv"
        assert result.strategy == "arxiv_rotation"

    @patch("core.entropy.urlopen", side_effect=TimeoutError("timeout"))
    def test_returns_none_on_failure(self, mock_urlopen, base_config):
        result = _strategy_arxiv_rotation(base_config)
        assert result is None


class TestVaultDensityDetection:
    def test_detects_densest_domain(self):
        notes = [
            MagicMock(tags=["philosophy", "ethics", "epistemology"]),
            MagicMock(tags=["philosophy", "ai"]),
            MagicMock(tags=["economics"]),
        ]
        result = _detect_vault_density(notes)
        assert result == "philosophy"

    def test_returns_none_for_empty_vault(self):
        result = _detect_vault_density([])
        assert result is None

    def test_returns_none_for_unknown_tags(self):
        notes = [MagicMock(tags=["zzz_unknown_tag"])]
        result = _detect_vault_density(notes)
        assert result is None

    def test_handles_mixed_tags(self):
        notes = [
            MagicMock(tags=["ai", "machine-learning", "deep-learning"]),
            MagicMock(tags=["economics", "markets"]),
        ]
        result = _detect_vault_density(notes)
        assert result == "ai"


class TestAdjacentPossibleStrategy:
    @patch("core.entropy.urlopen")
    def test_returns_concept_with_vault_notes(self, mock_urlopen, base_config):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_wiki_response("Cognitive Load")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        notes = [
            MagicMock(tags=["philosophy", "ethics"]),
            MagicMock(tags=["philosophy"]),
        ]
        result = _strategy_adjacent_possible(base_config, vault_notes=notes)

        assert result is not None
        assert result.strategy == "adjacent_possible"
        assert result.source == "wikipedia"

    @patch("core.entropy.urlopen")
    def test_uses_fallback_without_vault_notes(self, mock_urlopen, base_config):
        mock_resp = MagicMock()
        mock_resp.read.return_value = _make_wiki_response("Lambda Calculus")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _strategy_adjacent_possible(base_config, vault_notes=None)

        assert result is not None
        assert result.strategy == "adjacent_possible"


class TestFetchEntropyConcept:
    def test_disabled_returns_none(self):
        config = {"entropy": {"enabled": False}}
        result = fetch_entropy_concept(config)
        assert result is None

    def test_unknown_strategy_returns_none(self):
        config = {"entropy": {"enabled": True, "strategy": "unknown_strategy"}}
        result = fetch_entropy_concept(config)
        assert result is None

    @patch("core.entropy._strategy_curated_random")
    def test_dispatches_curated_random(self, mock_strategy, base_config):
        expected = EntropyConcept(
            title="Test",
            summary="Summary",
            source="wikipedia",
            domain="mathematics",
            strategy="curated_random",
        )
        mock_strategy.return_value = expected

        result = fetch_entropy_concept(base_config)
        assert result == expected
        mock_strategy.assert_called_once_with(base_config)

    @patch("core.entropy._strategy_arxiv_rotation")
    def test_dispatches_arxiv_rotation(self, mock_strategy):
        config = {"entropy": {"enabled": True, "strategy": "arxiv_rotation"}}
        expected = EntropyConcept(
            title="Paper",
            summary="Summary",
            source="arxiv",
            domain="math",
            strategy="arxiv_rotation",
        )
        mock_strategy.return_value = expected

        result = fetch_entropy_concept(config, run_count=5)
        assert result == expected
        mock_strategy.assert_called_once_with(config, 5)

    @patch("core.entropy._strategy_adjacent_possible")
    def test_dispatches_adjacent_possible(self, mock_strategy):
        config = {"entropy": {"enabled": True, "strategy": "adjacent_possible"}}
        notes = [MagicMock(tags=["ai"])]
        expected = EntropyConcept(
            title="Article",
            summary="Summary",
            source="wikipedia",
            domain="philosophy_of_mind",
            strategy="adjacent_possible",
        )
        mock_strategy.return_value = expected

        result = fetch_entropy_concept(config, vault_notes=notes)
        assert result == expected
        mock_strategy.assert_called_once_with(config, notes)

    @patch("core.entropy._strategy_curated_random", side_effect=Exception("boom"))
    def test_catches_exceptions(self, mock_strategy, base_config):
        result = fetch_entropy_concept(base_config)
        assert result is None
