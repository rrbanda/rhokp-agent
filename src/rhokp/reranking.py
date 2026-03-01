"""Optional cross-encoder reranking for improved retrieval precision.

Uses ``sentence-transformers`` to score each retrieved document against the
query with a cross-encoder model, then reorders by score.

Requires the ``sentence-transformers`` package::

    pip install rhokp[reranking]
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rhokp.models import OKPDocument

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def rerank(
    query: str,
    docs: list[OKPDocument],
    *,
    model: str = _DEFAULT_MODEL,
    top_k: int | None = None,
) -> list[OKPDocument]:
    """Rerank *docs* by cross-encoder relevance to *query*.

    Args:
        query: The original search query.
        docs: Documents to rerank.
        model: HuggingFace model name for the cross-encoder.
            Default: ``cross-encoder/ms-marco-MiniLM-L-6-v2``.
        top_k: Return only the top-k documents after reranking.
            If None, all documents are returned (just reordered).

    Returns:
        A new list of :class:`OKPDocument` sorted by cross-encoder score,
        highest first.

    Raises:
        ImportError: If ``sentence-transformers`` is not installed.
    """
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is required for reranking. "
            "Install it with: pip install rhokp[reranking]"
        ) from exc

    if not docs:
        return []

    encoder = CrossEncoder(model)
    pairs = [(query, doc.snippet or doc.title) for doc in docs]
    scores = encoder.predict(pairs)

    scored = sorted(zip(scores, docs), key=lambda x: float(x[0]), reverse=True)

    logger.debug(
        "Reranked %d docs for query=%r, top score=%.3f",
        len(docs),
        query,
        float(scored[0][0]) if scored else 0.0,
    )

    result = [doc for _, doc in scored]
    if top_k is not None:
        result = result[:top_k]
    return result
