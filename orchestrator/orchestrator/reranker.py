"""Cross-encoder re-ranking for improved retrieval precision.

Two-stage retrieval: retrieve top-K candidates from the vector store,
then re-rank with a cross-encoder to get the top-N most relevant results.
Dramatically improves precision for factual aviation queries.

Usage:
    reranker = CrossEncoderReranker()
    reranked = reranker.rerank(query, candidates, top_n=5)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default models
_DEFAULT_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    """Re-ranks retrieved documents using a cross-encoder model.

    Loads the model lazily on first use to avoid startup overhead
    when re-ranking isn't needed.
    """

    def __init__(self, model_name: str = _DEFAULT_CROSS_ENCODER) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._available = True

    def _load_model(self) -> bool:
        """Lazy-load the cross-encoder model."""
        if self._model is not None:
            return True
        if not self._available:
            return False

        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)
            logger.info("Loaded cross-encoder model: %s", self._model_name)
            return True
        except ImportError:
            logger.warning(
                "sentence-transformers not available; re-ranking disabled. "
                "Install with: pip install sentence-transformers"
            )
            self._available = False
            return False
        except Exception:
            logger.warning("Failed to load cross-encoder model", exc_info=True)
            self._available = False
            return False

    @property
    def available(self) -> bool:
        """Whether the re-ranker model is available."""
        if self._model is not None:
            return True
        return self._available

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int = 5,
        score_key: str = "rerank_score",
    ) -> list[dict[str, Any]]:
        """Re-rank documents by relevance to the query.

        Args:
            query: The search query.
            documents: List of document dicts, each must have a "content" key.
            top_n: Number of top results to return.
            score_key: Key name to store the re-rank score in each document.

        Returns:
            Top-N documents sorted by re-rank score (highest first).
            If the model is unavailable, returns the original documents
            truncated to top_n.
        """
        if not documents:
            return []

        if not self._load_model():
            return documents[:top_n]

        # Build query-document pairs for the cross-encoder
        pairs = [(query, doc.get("content", "")) for doc in documents]

        try:
            scores = self._model.predict(pairs)

            # Attach scores and sort
            scored_docs = []
            for doc, score in zip(documents, scores, strict=True):
                scored_doc = {**doc, score_key: float(score)}
                scored_docs.append(scored_doc)

            scored_docs.sort(key=lambda d: d[score_key], reverse=True)
            return scored_docs[:top_n]

        except Exception:
            logger.warning("Re-ranking failed; returning original order", exc_info=True)
            return documents[:top_n]
