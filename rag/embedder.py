"""Embedder for Tax Code (НК РФ) using Meno-Lite-0.1 embeddings.

Implements text chunking and embedding generation for RAG search.
Uses Meno-Lite-0.1 (НГУ, Russian, RAG-optimized) via sentence-transformers.

Parameters (from design.md):
    - chunk_size: 500 tokens
    - chunk_overlap: 50 tokens
    - embedding_model: ngs-meno/meno-lite-0.1
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# RAG parameters from design.md
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
EMBEDDING_MODEL = "ngs-meno/meno-lite-0.1"


@dataclass
class Chunk:
    """Text chunk with metadata."""
    article: int
    paragraph: str
    text: str
    date: str
    source: str
    chunk_index: int = 0
    embedding: List[float] = field(default_factory=list)

    @property
    def id(self) -> str:
        """Unique chunk ID."""
        return f"{self.article}_{self.paragraph}"

    @property
    def content(self) -> str:
        """Full content for embedding."""
        return f"Статья {self.article}, пункт {self.paragraph}: {self.text}"


class TaxCodeEmbedder:
    """Embeds Tax Code (НК РФ) chunks using Meno-Lite-0.1."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ):
        """Initialize embedder.

        Args:
            model_name: HuggingFace model name for embeddings.
            chunk_size: Size of each chunk in tokens.
            chunk_overlap: Overlap between chunks in tokens.
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        logger.info("Loading embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name)
        logger.info("Model loaded: %s", self.model.get_sentence_embedding_dimension())

    def load_corpus(self, filepath: str) -> List[Chunk]:
        """Load Tax Code corpus from JSON file.

        Args:
            filepath: Path to nk_rf.json.

        Returns:
            List of Chunk objects with text but no embeddings yet.
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Corpus not found: {filepath}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chunks = []
        for entry in data:
            chunk = Chunk(
                article=entry["article"],
                paragraph=entry["paragraph"],
                text=entry["text"],
                date=entry["date"],
                source=entry["source"],
            )
            chunks.append(chunk)

        logger.info("Loaded %d entries from %s", len(chunks), filepath)
        return chunks

    def chunk_text(self, chunks: List[Chunk]) -> List[Chunk]:
        """Split long texts into smaller chunks.

        For Tax Code articles, each entry is typically 1-2 paragraphs,
        so chunking is minimal. But we handle long texts gracefully.

        Args:
            chunks: List of Chunk objects.

        Returns:
            List of Chunk objects with potentially split texts.
        """
        result = []
        for chunk in chunks:
            text = chunk.text
            if len(text) <= self.chunk_size:
                result.append(chunk)
            else:
                # Split long text into overlapping chunks
                start = 0
                idx = 0
                while start < len(text):
                    end = start + self.chunk_size
                    slice_text = text[start:end]

                    # Try to break at sentence boundary
                    last_period = slice_text.rfind(".")
                    if last_period > self.chunk_size * 0.5:
                        slice_text = slice_text[: last_period + 1]

                    new_chunk = Chunk(
                        article=chunk.article,
                        paragraph=chunk.paragraph,
                        text=slice_text,
                        date=chunk.date,
                        source=chunk.source,
                        chunk_index=idx,
                    )
                    result.append(new_chunk)

                    start = end - self.chunk_overlap
                    idx += 1

        logger.info("Chunked %d entries -> %d chunks", len(chunks), len(result))
        return result

    def embed(self, chunks: List[Chunk]) -> List[Chunk]:
        """Generate embeddings for all chunks.

        Args:
            chunks: List of Chunk objects.

        Returns:
            List of Chunk objects with embeddings populated.
        """
        texts = [c.content for c in chunks]
        logger.info("Generating embeddings for %d chunks...", len(texts))

        embeddings = self.model.encode(
            texts,
            batch_size=32,
            show_progress_bar=True,
            normalize_embeddings=True,
        )

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding.tolist()

        logger.info("Embeddings generated: %d chunks, %d dimensions", len(chunks), len(chunks[0].embedding))
        return chunks

    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query.

        Args:
            query: Search query string.

        Returns:
            Normalized embedding vector.
        """
        embedding = self.model.encode(query, normalize_embeddings=True)
        return embedding.tolist()

    def save_embeddings(self, chunks: List[Chunk], filepath: str) -> None:
        """Save chunks with embeddings to JSON file.

        Args:
            chunks: List of Chunk objects with embeddings.
            filepath: Output path (e.g., rag/data/nk_rf_embedded.json).
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = []
        for chunk in chunks:
            data.append({
                "id": chunk.id,
                "article": chunk.article,
                "paragraph": chunk.paragraph,
                "text": chunk.text,
                "date": chunk.date,
                "source": chunk.source,
                "chunk_index": chunk.chunk_index,
                "embedding": chunk.embedding,
            })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("Saved %d chunks with embeddings to %s", len(data), filepath)
