"""Top-k search with article filtering for Tax Code (НК РФ) RAG.

Implements search with configurable k (default 5 per design.md),
article filtering, and result ranking by cosine similarity.

Parameters (from design.md):
    - k: 5 (top-k results)
    - similarity_threshold: 0.5 (min cosine similarity)
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from rag.embedder import TaxCodeEmbedder
from rag.vector_store import TaxCodeVectorStore

logger = logging.getLogger(__name__)

# Default search parameters from design.md
DEFAULT_TOP_K = 5
SIMILARITY_THRESHOLD = 0.5


@dataclass
class SearchResult:
    """Single search result with relevance score."""
    article: int
    paragraph: str
    text: str
    date: str
    source: str
    distance: float
    relevance: float  # 1 - distance (cosine similarity)

    @property
    def citation(self) -> str:
        """Format citation for answer synthesis.

        Returns:
            Citation string like "ст. 164 п. 1 НК РФ".
        """
        return f"ст. {self.article} п. {self.paragraph} НК РФ"


class TaxCodeSearcher:
    """Top-k search for Tax Code (НК РФ) with article filtering."""

    def __init__(
        self,
        embedder: Optional[TaxCodeEmbedder] = None,
        vector_store: Optional[TaxCodeVectorStore] = None,
        top_k: int = DEFAULT_TOP_K,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ):
        """Initialize searcher.

        Args:
            embedder: Optional embedder for query embeddings.
            vector_store: Optional vector store instance.
            top_k: Number of results to return.
            similarity_threshold: Minimum cosine similarity.
        """
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold

        if vector_store is None:
            self.vector_store = TaxCodeVectorStore()
        else:
            self.vector_store = vector_store

        if embedder is None:
            self.embedder = TaxCodeEmbedder()
        else:
            self.embedder = embedder

        # Connect embedder to vector store
        self.vector_store.set_embedder(self.embedder)

        logger.info(
            "TaxCodeSearcher initialized: top_k=%d, threshold=%.2f",
            top_k,
            similarity_threshold,
        )

    def search(
        self,
        query: str,
        article: Optional[int] = None,
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """Search for relevant Tax Code articles.

        Args:
            query: Search query string.
            article: Optional article number filter.
            top_k: Override default top_k.

        Returns:
            List of SearchResult objects sorted by relevance.
        """
        k = top_k or self.top_k

        logger.info("Searching '%s' (k=%d, article=%s)", query[:50], k, article)

        # Search in vector store
        raw_results = self.vector_store.search(
            query=query,
            top_k=k,
            article_filter=article,
        )

        # Convert to SearchResult with relevance score
        results = []
        for chunk, distance in raw_results:
            relevance = 1.0 - distance  # cosine similarity
            if relevance >= self.similarity_threshold:
                result = SearchResult(
                    article=chunk.article,
                    paragraph=chunk.paragraph,
                    text=chunk.text,
                    date=chunk.date,
                    source=chunk.source,
                    distance=distance,
                    relevance=relevance,
                )
                results.append(result)

        logger.info("Found %d results (threshold=%.2f)", len(results), self.similarity_threshold)
        return results

    def search_by_article(
        self,
        article: int,
        top_k: int = DEFAULT_TOP_K,
    ) -> List[SearchResult]:
        """Search within a specific article.

        Args:
            article: Article number (e.g., 164 for НДС).
            top_k: Number of results.

        Returns:
            List of SearchResult objects.
        """
        return self.search(query="", article=article, top_k=top_k)

    def get_citations(self, results: List[SearchResult]) -> List[str]:
        """Extract citations from search results.

        Args:
            results: List of SearchResult objects.

        Returns:
            List of citation strings.
        """
        return [r.citation for r in results]

    def format_answer(self, results: List[SearchResult]) -> str:
        """Format search results as a human-readable answer.

        Args:
            results: List of SearchResult objects.

        Returns:
            Formatted answer string with citations.
        """
        if not results:
            return "Норма не найдена."

        lines = []
        for result in results[:3]:  # Top 3 results
            lines.append(f"Согласно {result.citation}:")
            lines.append(result.text)
            lines.append("")

        return "\n".join(lines).strip()

    def preload(self, corpus_path: str) -> int:
        """Load corpus and index into vector store.

        This is the main entry point for RAG setup:
        1. Load Tax Code corpus
        2. Generate embeddings
        3. Add to vector store

        Args:
            corpus_path: Path to nk_rf.json.

        Returns:
            Number of chunks indexed.
        """
        logger.info("Preloading corpus from %s", corpus_path)

        # Load and chunk
        chunks = self.embedder.load_corpus(corpus_path)
        chunks = self.embedder.chunk_text(chunks)

        # Generate embeddings
        chunks = self.embedder.embed(chunks)

        # Add to vector store
        count = self.vector_store.add_chunks(chunks)

        logger.info("Preloaded %d chunks into vector store", count)
        return count
