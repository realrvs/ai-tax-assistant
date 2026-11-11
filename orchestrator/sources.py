"""1C API and RAG calls from orchestrator with traceparent propagation.

ADR-005: HTTP-сервисы 1С с JWT + HTTPS.
design.md: traceparent пробрасывается в HTTP-заголовке при вызове 1C API.
W3C traceparent format: 00-{trace_id}-{span_id}-{flags}

Covers:
- FR-001, FR-002: Call RAG and 1C sources from orchestrator
- OBS-C-02: traceparent propagated to all services
- NFR-SEC-006: HTTPS + JWT for 1C API
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from rag.search import TaxCodeSearcher, SearchResult

logger = logging.getLogger(__name__)

# Default 1C API base URL (from environment)
ONE_C_API_BASE = os.getenv("ONE_C_API_URL", "http://localhost:8080")
ONE_C_API_TIMEOUT = float(os.getenv("ONE_C_API_TIMEOUT", "5.0"))

# JWT token (from environment)
ONE_C_JWT_TOKEN = os.getenv("ONE_C_JWT_TOKEN", "")


@dataclass
class OneCBalanceResponse:
    """Response from GET /api/v1/taxes/balance."""
    tax: str
    balance: float
    as_of_date: str
    trace_id: str


@dataclass
class OneCCalculateResponse:
    """Response from POST /api/v1/taxes/calculate."""
    tax: str
    period: str
    amount: float
    rate: str
    article: str
    as_of_date: str
    trace_id: str


@dataclass
class OneCDocumentsResponse:
    """Response from GET /api/v1/documents/search."""
    total: int
    documents: List[Dict[str, Any]]
    trace_id: str


@dataclass
class RAGSearchResult:
    """RAG search result with metadata."""
    article: int
    paragraph: str
    text: str
    date: str
    source: str
    relevance: float
    citation: str  # "ст. XXX п. Y НК РФ"


class OneCAPI:
    """1C HTTP API client with JWT authentication and traceparent propagation.

    Endpoints:
    - GET /api/v1/taxes/balance?tax=nds
    - POST /api/v1/taxes/calculate
    - GET /api/v1/documents/search?tax=nds&from_date=...
    """

    def __init__(
        self,
        base_url: str = ONE_C_API_BASE,
        jwt_token: str = ONE_C_JWT_TOKEN,
        timeout: float = ONE_C_API_TIMEOUT,
    ):
        """Initialize 1C API client.

        Args:
            base_url: 1C HTTP services base URL.
            jwt_token: JWT bearer token.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.jwt_token = jwt_token
        self.timeout = timeout

        logger.info(
            "OneCAPI initialized: base_url=%s, timeout=%.1fs",
            self.base_url,
            self.timeout,
        )

    def _build_headers(self, traceparent: Optional[str] = None) -> Dict[str, str]:
        """Build HTTP headers with JWT and traceparent.

        Args:
            traceparent: W3C traceparent header value.

        Returns:
            Headers dict.
        """
        headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if traceparent:
            headers["traceparent"] = traceparent
        return headers

    def get_balance(self, tax: str, traceparent: Optional[str] = None) -> OneCBalanceResponse:
        """Call GET /api/v1/taxes/balance.

        Args:
            tax: Tax type (nds, profit, usn).
            traceparent: W3C traceparent for correlation.

        Returns:
            OneCBalanceResponse with balance data.

        Raises:
            httpx.HTTPError: If 1C API returns error.
        """
        url = f"{self.base_url}/api/v1/taxes/balance"
        params = {"tax": tax}
        headers = self._build_headers(traceparent)

        logger.info(
            "1C GET /taxes/balance tax=%s (traceparent=%s)",
            tax,
            traceparent[:20] if traceparent else "none",
        )

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()

            data = resp.json()
            return OneCBalanceResponse(
                tax=data.get("tax", tax),
                balance=float(data.get("balance", 0)),
                as_of_date=data.get("as_of_date", ""),
                trace_id=data.get("trace_id", ""),
            )

    def calculate_tax(
        self,
        tax: str,
        period: str,
        traceparent: Optional[str] = None,
    ) -> OneCCalculateResponse:
        """Call POST /api/v1/taxes/calculate.

        Args:
            tax: Tax type (nds, profit, usn).
            period: Period identifier (2025q1, etc.).
            traceparent: W3C traceparent for correlation.

        Returns:
            OneCCalculateResponse with calculated amount.

        Raises:
            httpx.HTTPError: If 1C API returns error.
        """
        url = f"{self.base_url}/api/v1/taxes/calculate"
        payload = {"tax": tax, "period": period}
        headers = self._build_headers(traceparent)

        logger.info(
            "1C POST /taxes/calculate tax=%s period=%s (traceparent=%s)",
            tax,
            period,
            traceparent[:20] if traceparent else "none",
        )

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

            data = resp.json()
            return OneCCalculateResponse(
                tax=data.get("tax", tax),
                period=data.get("period", period),
                amount=float(data.get("amount", 0)),
                rate=data.get("rate", ""),
                article=data.get("article", ""),
                as_of_date=data.get("as_of_date", ""),
                trace_id=data.get("trace_id", ""),
            )

    def search_documents(
        self,
        tax: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        traceparent: Optional[str] = None,
    ) -> OneCDocumentsResponse:
        """Call GET /api/v1/documents/search.

        Args:
            tax: Optional tax type filter.
            from_date: Optional start date.
            to_date: Optional end date.
            traceparent: W3C traceparent for correlation.

        Returns:
            OneCDocumentsResponse with document list.

        Raises:
            httpx.HTTPError: If 1C API returns error.
        """
        url = f"{self.base_url}/api/v1/documents/search"
        params = {}
        if tax:
            params["tax"] = tax
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date

        headers = self._build_headers(traceparent)

        logger.info(
            "1C GET /documents/search params=%s (traceparent=%s)",
            params,
            traceparent[:20] if traceparent else "none",
        )

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()

            data = resp.json()
            return OneCDocumentsResponse(
                total=int(data.get("total", 0)),
                documents=data.get("documents", []),
                trace_id=data.get("trace_id", ""),
            )

    def is_available(self) -> bool:
        """Check if 1C API is reachable.

        Returns:
            True if 1C API responds to health check.
        """
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{self.base_url}/api/v1/health")
                return resp.status_code == 200
        except Exception:
            return False


class RAGSource:
    """RAG search source wrapper.

    Wraps TaxCodeSearcher for use in the orchestrator.
    """

    def __init__(self, searcher: Optional[TaxCodeSearcher] = None):
        """Initialize RAG source.

        Args:
            searcher: Optional pre-configured TaxCodeSearcher.
        """
        self.searcher = searcher
        logger.info("RAGSource initialized")

    def search(
        self,
        query: str,
        article: Optional[int] = None,
        top_k: int = 5,
        traceparent: Optional[str] = None,
    ) -> List[RAGSearchResult]:
        """Search Tax Code (НК РФ) using RAG.

        Args:
            query: Search query.
            article: Optional article filter.
            top_k: Number of results.
            traceparent: W3C traceparent for correlation.

        Returns:
            List of RAGSearchResult objects.
        """
        if self.searcher is None:
            logger.warning("RAG searcher not initialized, returning empty results")
            return []

        logger.info(
            "RAG search query=%s (traceparent=%s)",
            query[:50],
            traceparent[:20] if traceparent else "none",
        )

        results = self.searcher.search(query, article=article, top_k=top_k)

        return [
            RAGSearchResult(
                article=r.article,
                paragraph=r.paragraph,
                text=r.text,
                date=r.date,
                source=r.source,
                relevance=r.relevance,
                citation=r.citation,
            )
            for r in results
        ]

    def preload(self, corpus_path: str) -> int:
        """Preload corpus into vector store.

        Args:
            corpus_path: Path to nk_rf.json.

        Returns:
            Number of chunks indexed.
        """
        if self.searcher is None:
            from rag.search import TaxCodeSearcher
            from rag.embedder import TaxCodeEmbedder

            embedder = TaxCodeEmbedder()
            self.searcher = TaxCodeSearcher(embedder=embedder)

        return self.searcher.preload(corpus_path)


class SourceOrchestrator:
    """Orchestrates calls to 1C and RAG sources.

    Generates traceparent, propagates to all services,
    and aggregates results for the synthesizer.
    """

    def __init__(
        self,
        one_c_api: Optional[OneCAPI] = None,
        rag_source: Optional[RAGSource] = None,
    ):
        """Initialize source orchestrator.

        Args:
            one_c_api: Optional OneCAPI instance.
            rag_source: Optional RAGSource instance.
        """
        self.one_c_api = one_c_api or OneCAPI()
        self.rag_source = rag_source or RAGSource()

        logger.info("SourceOrchestrator initialized")

    def generate_traceparent(self) -> str:
        """Generate W3C traceparent header.

        Format: 00-{32-char-trace_id}-{16-char-span_id}-01

        Returns:
            W3C traceparent string.
        """
        trace_id = uuid4().hex[:32]
        span_id = uuid4().hex[:16]
        return f"00-{trace_id}-{span_id}-01"

    def fetch_sources(
        self,
        query: str,
        intent: str,  # "explain", "data", "combined"
        tax_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch data from appropriate sources based on intent.

        Pipeline:
        1. Generate traceparent
        2. Call RAG if intent is "explain" or "combined"
        3. Call 1C if intent is "data" or "combined"
        4. Aggregate results

        Args:
            query: User query.
            intent: Classified intent (explain/data/combined).
            tax_type: Optional tax type (nds/profit/usn).

        Returns:
            Dict with rag_results and one_c_data.
        """
        # Step 1: Generate traceparent for correlation
        traceparent = self.generate_traceparent()

        result = {
            "rag_results": [],
            "one_c_data": None,
            "traceparent": traceparent,
            "error": None,
        }

        # Step 2: RAG search (explain, combined)
        if intent in ("explain", "combined"):
            try:
                rag_results = self.rag_source.search(
                    query=query,
                    top_k=5,
                    traceparent=traceparent,
                )
                result["rag_results"] = [
                    {
                        "article": r.article,
                        "paragraph": r.paragraph,
                        "text": r.text,
                        "date": r.date,
                        "source": r.source,
                        "citation": r.citation,
                    }
                    for r in rag_results
                ]
                logger.info("RAG: %d results", len(rag_results))
            except Exception as e:
                logger.error("RAG search failed: %s", e)
                result["error"] = f"RAG error: {e}"

        # Step 3: 1C API call (data, combined)
        if intent in ("data", "combined") and tax_type:
            try:
                balance = self.one_c_api.get_balance(
                    tax=tax_type,
                    traceparent=traceparent,
                )
                result["one_c_data"] = {
                    "tax": balance.tax,
                    "balance": balance.balance,
                    "as_of_date": balance.as_of_date,
                    "trace_id": balance.trace_id,
                }
                logger.info("1C balance: %.2f for %s", balance.balance, balance.tax)
            except Exception as e:
                logger.error("1C API call failed: %s", e)
                result["one_c_data"] = {
                    "error": f"1C unavailable: {e}",
                    "as_of_date": None,
                }

        return result
