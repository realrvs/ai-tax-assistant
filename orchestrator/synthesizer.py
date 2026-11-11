"""Answer synthesizer with citation validation.

Implements answer synthesis via GigaChat 3.5 Reasoning + citation validation.
design.md prompt template + NFR-SEC-003 validation.

Covers:
- FR-004: Synthesize answer combining RAG + 1C data with mandatory citation
- NFR-SEC-003: Reject answers without citation (hallucination protection)
- TM-05, TM-07: Insecure output handling, Misinformation
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Citation validation regex from design.md
CITATION_PATTERN = re.compile(
    r"ст\.\s*\d+\s*п\.\s*\d+\s*НК\s*РФ",
    re.IGNORECASE | re.UNICODE,
)

# Prompt template from design.md
PROMPT_TEMPLATE = """Ты — налоговый ассистент. Отвечай на русском языке, кратко (до 300 слов).

Данные из НК РФ (RAG):
{rag_results}

Данные из 1С:
{one_c_data}

Правила:
1. Каждый факт из НК РФ должен содержать ссылку в формате «ст. XXX п. Y НК РФ».
2. Каждый факт из 1С должен содержать дату актуальности: «данные на DD.MM.YYYY».
3. Если RAG не нашёл статью — явно напиши «Норма не найдена».
4. Если 1С недоступна — напиши «Данные 1С временно недоступны».
5. Не генерируй ссылки на статьи, которых нет в RAG-результатах.

Ответ:
"""


@dataclass
class SynthesisRequest:
    """Request for answer synthesis."""
    query: str
    rag_results: List[dict] = field(default_factory=list)
    one_c_data: Optional[dict] = None
    traceparent: Optional[str] = None


@dataclass
class SynthesisResponse:
    """Response from answer synthesis."""
    answer: str
    citations: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    citation_valid: bool = True
    error: Optional[str] = None


class GigaChatClient:
    """GigaChat API client wrapper.

    For MVP: uses a mock response if no API key is provided.
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize GigaChat client.

        Args:
            api_key: GigaChat API key (from environment).
        """
        self.api_key = api_key
        self._is_mock = not api_key

    def generate(self, prompt: str) -> str:
        """Generate answer using GigaChat 3.5 Reasoning.

        Args:
            prompt: Formatted prompt with RAG and 1C data.

        Returns:
            Generated answer string.
        """
        if self._is_mock:
            logger.warning("No GigaChat API key, using mock response")
            return self._mock_response(prompt)

        # TODO: Implement real GigaChat API call
        # Endpoint: https://gigachat.devices.sberbank.ru/api/v1/models
        # Auth: OAuth token via /auth
        logger.info("Calling GigaChat API...")
        raise NotImplementedError("GigaChat API integration not implemented")

    def _mock_response(self, prompt: str) -> str:
        """Mock response for testing without API key."""
        return (
            "Согласно ст. 164 п. 1 НК РФ, ставка НДС составляет 20%. "
            "Данные из 1С: сальдо ЕНС по НДС составляет 150 000 руб. "
            "данные на 31.03.2025."
        )


class Synthesizer:
    """Answer synthesizer with citation validation."""

    def __init__(self, gigachat_client: Optional[GigaChatClient] = None):
        """Initialize synthesizer.

        Args:
            gigachat_client: Optional GigaChat client.
        """
        self.client = gigachat_client or GigaChatClient()

        logger.info("Synthesizer initialized")

    def synthesize(self, request: SynthesisRequest) -> SynthesisResponse:
        """Synthesize answer from RAG and 1C data.

        Args:
            request: SynthesisRequest with query, RAG results, and 1C data.

        Returns:
            SynthesisResponse with answer and validation status.
        """
        # Build prompt
        prompt = self._build_prompt(request)

        # Generate answer
        logger.info("Synthesizing answer (traceparent=%s)", request.traceparent)
        answer = self.client.generate(prompt)

        # Validate citations
        citations = self._extract_citations(answer)
        citation_valid = self._validate_citation(answer, request.rag_results)

        # Determine sources used
        sources_used = []
        if request.rag_results:
            sources_used.append("rag")
        if request.one_c_data:
            sources_used.append("1c")

        return SynthesisResponse(
            answer=answer,
            citations=citations,
            sources_used=sources_used,
            citation_valid=citation_valid,
        )

    def _build_prompt(self, request: SynthesisRequest) -> str:
        """Build prompt for synthesis.

        Args:
            request: SynthesisRequest.

        Returns:
            Formatted prompt string.
        """
        # Format RAG results
        if request.rag_results:
            rag_text = "\n".join(
                f"Статья {r.get('article', '?')}, пункт {r.get('paragraph', '?')}: {r.get('text', '')}"
                for r in request.rag_results[:3]  # Top 3 results
            )
        else:
            rag_text = "RAG не вернул результатов."

        # Format 1C data
        if request.one_c_data:
            one_c_text = f"Сальдо ЕНС: {request.one_c_data.get('balance', 'N/A')} руб. "
            one_c_text += f"данные на {request.one_c_data.get('as_of_date', 'N/A')}"
        else:
            one_c_text = "Данные 1С недоступны."

        return PROMPT_TEMPLATE.format(rag_results=rag_text, one_c_data=one_c_text)

    def _extract_citations(self, answer: str) -> List[str]:
        """Extract citations from answer text.

        Args:
            answer: Generated answer string.

        Returns:
            List of citation strings (e.g., "ст. 164 п. 1 НК РФ").
        """
        return CITATION_PATTERN.findall(answer)

    def _validate_citation(self, answer: str, rag_results: List[dict]) -> bool:
        """Validate that answer contains valid citations.

        NFR-SEC-003: 100% ответов содержат источник.
        If RAG returned results, answer MUST contain at least one citation.

        Args:
            answer: Generated answer string.
            rag_results: RAG search results.

        Returns:
            True if citations are valid, False otherwise.
        """
        if not rag_results:
            # No RAG results, no citation required
            return True

        citations = self._extract_citations(answer)
        if not citations:
            logger.warning("Answer has no citations (NFR-SEC-003 violation)")
            return False

        # Validate that citations exist in RAG results
        rag_articles = {r.get("article") for r in rag_results}
        for citation in citations:
            # Extract article number from citation (e.g., "ст. 164 п. 1" -> 164)
            match = re.search(r"ст\.\s*(\d+)", citation)
            if match:
                article = int(match.group(1))
                if article not in rag_articles:
                    logger.warning("Citation ст. %d not found in RAG results (hallucination)", article)
                    return False

        return True

    def validate_and_reject(self, response: SynthesisResponse) -> SynthesisResponse:
        """Validate response and reject if citations are missing.

        NFR-SEC-003: Answer without source is rejected.

        Args:
            response: SynthesisResponse to validate.

        Returns:
            Validated response (or error if rejected).
        """
        if not response.citation_valid:
            logger.error("Answer rejected: no valid citations (NFR-SEC-003)")
            return SynthesisResponse(
                answer="Не удалось подтвердить ответ источником. Пожалуйста, уточните запрос.",
                citation_valid=False,
                error="No valid citations found",
            )

        return response
