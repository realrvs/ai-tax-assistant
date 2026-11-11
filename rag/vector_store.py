"""Chroma vector database for Tax Code (НК РФ) RAG search.

Persistent mode: data stored on disk, survives restarts.
ADR-002: RAG with mandatory citation + Chroma.

Parameters (from design.md):
    - persist_directory: rag/data/chroma_db
    - embedding_function: Meno-Lite-0.1
    - n_results: 5 (top-k)
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import chromadb
from chromadb.config import Settings

from rag.embedder import TaxCodeEmbedder, Chunk

logger = logging.getLogger(__name__)

COLLECTION_NAME = "nk_rf"


class TaxCodeVectorStore:
    """Chroma vector store for Tax Code (НК РФ) articles."""

    def __init__(
        self,
        persist_directory: str = "rag/data/chroma_db",
        embedding_function: Optional[TaxCodeEmbedder] = None,
    ):
        """Initialize Chroma vector store.

        Args:
            persist_directory: Directory for persistent storage.
            embedding_function: Optional embedder for query embeddings.
        """
        path = Path(persist_directory)
        path.mkdir(parents=True, exist_ok=True)

        logger.info("Initializing ChromaDB at %s", persist_directory)

        self.client = chromadb.PersistentClient(
            path=str(path),
            settings=Settings(anonymized_telemetry=False),
        )

        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # cosine similarity for embeddings
        )

        self.embedder = embedding_function
        logger.info("Collection '%s' ready: %d documents", COLLECTION_NAME, self.collection.count())

    def add_chunks(self, chunks: List[Chunk]) -> int:
        """Add chunks to the vector store.

        Args:
            chunks: List of Chunk objects with embeddings.

        Returns:
            Number of documents added.
        """
        if not chunks:
            logger.warning("No chunks to add")
            return 0

        ids = [c.id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [
            {
                "article": c.article,
                "paragraph": str(c.paragraph),
                "date": c.date,
                "source": c.source,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ]
        embeddings = [c.embedding for c in chunks]

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        logger.info("Added %d chunks to collection '%s'", len(chunks), COLLECTION_NAME)
        return len(chunks)

    def search(
        self,
        query: str,
        top_k: int = 5,
        article_filter: Optional[int] = None,
    ) -> List[Tuple[Chunk, float]]:
        """Search for relevant articles.

        Args:
            query: Search query string.
            top_k: Number of results (default 5 per design.md).
            article_filter: Optional article number filter.

        Returns:
            List of (Chunk, distance) tuples, sorted by relevance.
        """
        if self.embedder is None:
            raise ValueError("Embedder not set. Call set_embedder() first.")

        query_embedding = self.embedder.embed_query(query)

        # Build where filter
        where = {}
        if article_filter is not None:
            where["article"] = article_filter

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        for i in range(len(results["ids"][0])):
            chunk = Chunk(
                article=int(results["metadatas"][0][i]["article"]),
                paragraph=results["metadatas"][0][i]["paragraph"],
                text=results["documents"][0][i],
                date=results["metadatas"][0][i]["date"],
                source=results["metadatas"][0][i]["source"],
            )
            distance = results["distances"][0][i]
            chunks.append((chunk, distance))

        logger.info(
            "Search '%s': %d results (top_k=%d)",
            query[:50],
            len(chunks),
            top_k,
        )
        return chunks

    def count(self) -> int:
        """Return number of documents in the collection."""
        return self.collection.count()

    def delete_collection(self) -> None:
        """Delete the entire collection. Use with caution."""
        self.client.delete_collection(COLLECTION_NAME)
        logger.info("Deleted collection '%s'", COLLECTION_NAME)

    def set_embedder(self, embedder: TaxCodeEmbedder) -> None:
        """Set the embedder for query embeddings.

        Args:
            embedder: TaxCodeEmbedder instance.
        """
        self.embedder = embedder
