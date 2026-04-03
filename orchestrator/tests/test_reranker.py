"""Tests for cross-encoder re-ranking."""

from __future__ import annotations

from unittest.mock import MagicMock

from orchestrator.reranker import CrossEncoderReranker


class TestRerankerFallback:
    """Test re-ranker behavior when model is unavailable."""

    def test_unavailable_returns_truncated(self) -> None:
        reranker = CrossEncoderReranker()
        reranker._available = False  # Simulate unavailable model

        docs = [
            {"content": "doc1", "distance": 0.1},
            {"content": "doc2", "distance": 0.2},
            {"content": "doc3", "distance": 0.3},
        ]
        result = reranker.rerank("query", docs, top_n=2)
        assert len(result) == 2
        assert result[0]["content"] == "doc1"

    def test_empty_documents(self) -> None:
        reranker = CrossEncoderReranker()
        assert reranker.rerank("query", [], top_n=5) == []


class TestRerankerWithMock:
    """Test re-ranker with a mocked cross-encoder model."""

    def test_reranking_reorders_by_score(self) -> None:
        reranker = CrossEncoderReranker()
        mock_model = MagicMock()
        # Return scores that reverse the original order
        mock_model.predict.return_value = [0.1, 0.9, 0.5]
        reranker._model = mock_model

        docs = [
            {"content": "least relevant"},
            {"content": "most relevant"},
            {"content": "medium relevant"},
        ]
        result = reranker.rerank("test query", docs, top_n=2)

        assert len(result) == 2
        assert result[0]["content"] == "most relevant"
        assert result[1]["content"] == "medium relevant"
        assert result[0]["rerank_score"] == 0.9

    def test_custom_score_key(self) -> None:
        reranker = CrossEncoderReranker()
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.5, 0.8]
        reranker._model = mock_model

        docs = [{"content": "a"}, {"content": "b"}]
        result = reranker.rerank("query", docs, top_n=2, score_key="my_score")
        assert "my_score" in result[0]

    def test_predict_failure_returns_original(self) -> None:
        reranker = CrossEncoderReranker()
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("Model error")
        reranker._model = mock_model

        docs = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
        result = reranker.rerank("query", docs, top_n=2)
        assert len(result) == 2
        assert result[0]["content"] == "a"  # Original order preserved


class TestRerankerAvailability:
    def test_available_when_model_loaded(self) -> None:
        reranker = CrossEncoderReranker()
        reranker._model = MagicMock()
        assert reranker.available is True

    def test_available_before_load(self) -> None:
        reranker = CrossEncoderReranker()
        assert reranker.available is True  # Hasn't tried to load yet

    def test_unavailable_after_failed_load(self) -> None:
        reranker = CrossEncoderReranker()
        reranker._available = False
        assert reranker.available is False
