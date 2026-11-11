"""Tests for RAG search accuracy (TC-001, TC-002, TC-003).

Covers:
- TC-001: RAG находит ставку НДС (NFR-002: precision ≥ 90%)
- TC-002: RAG находит срок уплаты (NFR-002: precision ≥ 90%)
- TC-003: RAG не галлюцинирует (NFR-SEC-003: citation ≥ 95%)

NFR-002: RAG precision ≥ 90% on reference query set.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from rag.embedder import TaxCodeEmbedder
from rag.search import TaxCodeSearcher, SearchResult

# Reference query set for NFR-002 (precision ≥ 90%)
# Each query has expected article numbers that should be in top-k results
REFERENCE_QUERIES = [
    {
        "query": "Какая ставка НДС в 2026 году?",
        "expected_articles": [164],
        "description": "Ставка НДС",
    },
    {
        "query": "Срок уплаты НДС за квартал",
        "expected_articles": [167],
        "description": "Срок уплаты НДС",
    },
    {
        "query": "Налоговые вычеты по НДС",
        "expected_articles": [171, 172],
        "description": "Вычеты НДС",
    },
    {
        "query": "Возмещение НДС при переплате",
        "expected_articles": [176],
        "description": "Возмещение НДС",
    },
    {
        "query": "Налоговый период по НДС",
        "expected_articles": [166],
        "description": "Налоговый период",
    },
    {
        "query": "Объект налогообложения НДС",
        "expected_articles": [153],
        "description": "Объект НДС",
    },
    {
        "query": "Налоговая база по НДС",
        "expected_articles": [154],
        "description": "Налоговая база",
    },
    {
        "query": "Ставка 10 процентов НДС",
        "expected_articles": [164],
        "description": "Ставка 10%",
    },
    {
        "query": "Экспорт товаров ставка НДС",
        "expected_articles": [164],
        "description": "Экспорт 0%",
    },
    {
        "query": "Норма не существует такая",
        "expected_articles": [],
        "description": "Нет нормы (галлюцинация тест)",
    },
]


def _create_searcher(corpus_path: str) -> TaxCodeSearcher:
    """Create and preload a TaxCodeSearcher with the given corpus."""
    embedder = TaxCodeEmbedder()
    searcher = TaxCodeSearcher(embedder=embedder, top_k=5)
    searcher.preload(corpus_path)
    return searcher


class TestRAGAccuracy:
    """TC-001, TC-002: RAG search accuracy tests (NFR-002: precision ≥ 90%)."""

    @pytest.fixture(scope="class")
    def searcher(self, tmp_path_factory):
        """Create a searcher with the reference corpus."""
        corpus_path = Path("rag/data/nk_rf.json")
        if not corpus_path.exists():
            pytest.skip("Corpus not found: rag/data/nk_rf.json")
        return _create_searcher(str(corpus_path))

    @pytest.mark.parametrize(
        "ref_query",
        REFERENCE_QUERIES,
        ids=lambda q: q["description"],
    )
    def test_rag_finds_expected_articles(self, searcher, ref_query):
        """TC-001/TC-002: RAG finds expected articles in top-k results.

        NFR-002: ≥ 45 из 50 запросов находят правильную статью в top-3.
        Для нашего набора из 10 запросов: ≥ 9 должны найти хотя бы одну
        ожидаемую статью в top-k (k=5).
        """
        query = ref_query["query"]
        expected = ref_query["expected_articles"]
        description = ref_query["description"]

        results = searcher.search(query, top_k=5)

        if not expected:
            # TC-003: query with no expected articles should return empty or "not found"
            assert len(results) == 0, (
                f"TC-003 failed: '{description}' returned {len(results)} results, "
                f"expected 0 (no hallucination)"
            )
            return

        # Extract article numbers from results
        found_articles = [r.article for r in results]

        # At least one expected article must be in top-k
        hit = any(article in found_articles for article in expected)

        assert hit, (
            f"TC-001/TC-002 failed: '{description}'\n"
            f"Query: {query}\n"
            f"Expected articles: {expected}\n"
            f"Found articles: {found_articles}\n"
            f"Results: {[r.citation for r in results]}"
        )

    def test_rag_precision_on_reference_set(self, searcher):
        """TC-001/TC-002: Overall precision ≥ 90% on reference query set.

        NFR-002: ≥ 45 из 50 запросов находят правильную статью в top-3.
        Для нашего набора из 10 запросов (9 с ожидаемыми статьями + 1 без):
        precision = hits / total_with_expectations ≥ 90%.
        """
        hits = 0
        total = 0

        for ref_query in REFERENCE_QUERIES:
            expected = ref_query["expected_articles"]
            if not expected:
                continue  # Skip TC-003 (no expected articles)

            total += 1
            results = searcher.search(ref_query["query"], top_k=5)
            found_articles = [r.article for r in results]

            if any(article in found_articles for article in expected):
                hits += 1

        precision = hits / total if total > 0 else 0

        assert precision >= 0.9, (
            f"NFR-002 failed: precision {precision:.2%} < 90%\n"
            f"Hits: {hits}/{total}"
        )


class TestRAGNoHallucination:
    """TC-003: RAG does not hallucinate articles."""

    @pytest.fixture(scope="class")
    def searcher(self, tmp_path_factory):
        """Create a searcher with the reference corpus."""
        corpus_path = Path("rag/data/nk_rf.json")
        if not corpus_path.exists():
            pytest.skip("Corpus not found: rag/data/nk_rf.json")
        return _create_searcher(str(corpus_path))

    def test_rag_returns_not_found_for_unknown_query(self, searcher):
        """TC-003: Unknown query returns empty results (no hallucination).

        NFR-SEC-003: 100% ответов содержат источник.
        Если источник не найден — возвращаем «Норма не найдена».
        """
        results = searcher.search("Какая ставка налога на луну?", top_k=5)

        assert len(results) == 0, (
            "TC-003 failed: RAG returned results for unknown query (hallucination)\n"
            f"Results: {[r.citation for r in results]}"
        )

    def test_rag_format_answer_returns_not_found(self, searcher):
        """TC-003: format_answer returns 'Норма не найдена' for empty results."""
        results = searcher.search("Какая ставка налога на луну?", top_k=5)
        answer = searcher.format_answer(results)

        assert "Норма не найдена" in answer, (
            f"TC-003 failed: format_answer should return 'Норма не найдена'\n"
            f"Got: {answer}"
        )


class TestSearchResultFormatting:
    """Utility tests for SearchResult formatting."""

    def test_citation_format(self):
        """Test citation formatting: ст. XXX п. Y НК РФ."""
        result = SearchResult(
            article=164,
            paragraph="1",
            text="test",
            date="2026-01-01",
            source="НК РФ",
            distance=0.1,
            relevance=0.9,
        )

        assert result.citation == "ст. 164 п. 1 НК РФ"

    def test_format_answer_with_results(self):
        """Test format_answer with valid results."""
        results = [
            SearchResult(
                article=164,
                paragraph="1",
                text="Ставка НДС 20%",
                date="2026-01-01",
                source="НК РФ",
                distance=0.1,
                relevance=0.9,
            ),
        ]

        answer = TaxCodeSearcher().format_answer(results)

        assert "ст. 164 п. 1 НК РФ" in answer
        assert "Ставка НДС 20%" in answer


class TestEmbedder:
    """Tests for TaxCodeEmbedder."""

    def test_load_corpus(self):
        """Test loading the Tax Code corpus."""
        corpus_path = Path("rag/data/nk_rf.json")
        if not corpus_path.exists():
            pytest.skip("Corpus not found")

        embedder = TaxCodeEmbedder()
        chunks = embedder.load_corpus(str(corpus_path))

        assert len(chunks) > 0, "Corpus should have at least one entry"
        assert all(hasattr(c, "article") for c in chunks)
        assert all(hasattr(c, "paragraph") for c in chunks)
        assert all(hasattr(c, "text") for c in chunks)

    def test_chunk_text_short(self):
        """Test chunking short text (no split)."""
        embedder = TaxCodeEmbedder(chunk_size=500)
        from rag.embedder import Chunk

        chunks = [
            Chunk(
                article=164,
                paragraph="1",
                text="Короткий текст.",
                date="2026-01-01",
                source="НК РФ",
            ),
        ]

        result = embedder.chunk_text(chunks)
        assert len(result) == 1, "Short text should not be split"

    def test_embed_query(self):
        """Test query embedding generation."""
        embedder = TaxCodeEmbedder()
        embedding = embedder.embed_query("Какая ставка НДС?")

        assert isinstance(embedding, list)
        assert len(embedding) > 0
        # Normalized embeddings should have norm ≈ 1.0
        import math
        norm = math.sqrt(sum(e ** 2 for e in embedding))
        assert abs(norm - 1.0) < 0.01, f"Normalized embedding should have norm ≈ 1.0, got {norm}"


class TestVectorStore:
    """Tests for TaxCodeVectorStore."""

    def test_add_and_search(self):
        """Test adding chunks and searching."""
        from rag.embedder import TaxCodeEmbedder, Chunk
        from rag.vector_store import TaxCodeVectorStore

        embedder = TaxCodeEmbedder()
        store = TaxCodeVectorStore()
        store.set_embedder(embedder)

        # Add a test chunk
        chunks = [
            Chunk(
                article=164,
                paragraph="1",
                text="Ставка НДС составляет 20 процентов",
                date="2026-01-01",
                source="НК РФ",
            ),
        ]
        chunks = embedder.embed(chunks)
        store.add_chunks(chunks)

        # Search
        results = store.search("Ставка НДС", top_k=1)
        assert len(results) >= 1, "Should find at least one result"

    def test_article_filter(self):
        """Test searching with article filter."""
        from rag.embedder import TaxCodeEmbedder, Chunk
        from rag.vector_store import TaxCodeVectorStore

        embedder = TaxCodeEmbedder()
        store = TaxCodeVectorStore()
        store.set_embedder(embedder)

        # Add chunks for different articles
        chunks = [
            Chunk(article=164, paragraph="1", text="НДС 20%", date="2026-01-01", source="НК РФ"),
            Chunk(article=171, paragraph="1", text="Вычеты НДС", date="2026-01-01", source="НК РФ"),
        ]
        chunks = embedder.embed(chunks)
        store.add_chunks(chunks)

        # Search with article filter
        results = store.search("НДС", top_k=5, article_filter=164)
        found_articles = [r[0].article for r in results]

        # All results should be from article 164
        assert all(a == 164 for a in found_articles), (
            f"Article filter failed: expected all 164, got {found_articles}"
        )
