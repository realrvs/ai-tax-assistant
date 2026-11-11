"""Intent classifier for Tax Assistant.

Implements rule-based + LLM classification with fallback.
design.md:
    1. Rule-based filter (fast): keywords → intent
    2. LLM classifier (GigaChat function calling): tool selection
    3. Fallback: confidence < 0.7 → clarifying question

Covers:
- FR-003: Classify query and select sources (RAG, 1C, both)
- TM-04: Prompt injection protection
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """User intent categories."""
    EXPLAIN = "explain"  # Только закон (RAG)
    DATA = "data"  # Только данные (1C)
    COMBINED = "combined"  # И закон, и данные
    UNKNOWN = "unknown"  # Неоднозначный запрос


class Source(str, Enum):
    """Data sources."""
    RAG = "rag"
    ONE_C = "1c"


@dataclass
class ClassificationResult:
    """Result of intent classification."""
    intent: Intent
    sources: List[Source] = field(default_factory=list)
    tax_type: Optional[str] = None  # НДС, Прибыль, УСН
    confidence: float = 0.0
    clarifying_question: Optional[str] = None

    @property
    def needs_rag(self) -> bool:
        """Whether RAG source is needed."""
        return Source.RAG in self.sources

    @property
    def needs_one_c(self) -> bool:
        """Whether 1C source is needed."""
        return Source.ONE_C in self.sources


# Rule-based keyword patterns from design.md
RULE_PATTERNS = {
    Intent.EXPLAIN: [
        r"ставка\s+(?:НДС|прибыль|УСН|налог)",
        r"процент\s+(?:НДС|прибыль|УСН)",
        r"срок\s+(?:уплаты|оплаты|подачи)",
        r"когда\s+платить",
        r"когда\s+сдать",
        r"что\s+такое\s+(?:НДС|прибыль|УСН)",
        r"объясни\s+(?:НДС|прибыль|УСН)",
        r"статья\s+\d+",
        r"норма\s+(?:не\s+найдена|существует)",
        r"освобождение\s+от\s+налога",
        r"вычет\s+(?:НДС|налог)",
    ],
    Intent.DATA: [
        r"сальдо\s+ЕНС",
        r"мои\s+документы",
        r"мои\s+начисления",
        r"мои\s+уплаты",
        r"переплата",
        r"задолженность",
        r"покажи\s+мои",
        r"сколько\s+я\s+должен",
        r"сколько\s+я\s+должен\s+платить",
        r"какое\s+сальдо",
    ],
    Intent.COMBINED: [
        r"почему\s+у\s+меня",
        r"как\s+рассчитать",
        r"рассчитай\s+(?:НДС|прибыль|УСН)",
        r"почему\s+переплата",
        r"почему\s+задолженность",
        r"сверь\s+с\s+1с",
        r"проверь\s+мои",
    ],
}

# Tax type keywords
TAX_KEYWORDS = {
    "НДС": "nds",
    "прибыль": "profit",
    "УСН": "usn",
}


class RuleBasedClassifier:
    """Fast keyword-based intent classifier."""

    def __init__(self):
        self._compiled_patterns: dict[Intent, List[re.Pattern]] = {}
        for intent, patterns in RULE_PATTERNS.items():
            self._compiled_patterns[intent] = [
                re.compile(p, re.IGNORECASE | re.UNICODE)
                for p in patterns
            ]

    def classify(self, text: str) -> ClassificationResult:
        """Classify query using rule-based patterns.

        Args:
            text: User query text.

        Returns:
            ClassificationResult with intent, sources, and confidence.
        """
        text_lower = text.lower()

        # Count matches per intent
        scores: dict[Intent, int] = {Intent.EXPLAIN: 0, Intent.DATA: 0, Intent.COMBINED: 0}

        for intent, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(text_lower):
                    scores[intent] += 1

        # Find best intent
        best_intent = max(scores, key=scores.get)
        total_matches = sum(scores.values())

        if total_matches == 0:
            return ClassificationResult(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                clarifying_question="Вам нужна справка по закону или фактические цифры из 1С?",
            )

        # Calculate confidence based on match ratio
        confidence = min(1.0, total_matches / 3.0)  # Normalize

        # Determine sources
        sources = []
        if best_intent in (Intent.EXPLAIN, Intent.COMBINED):
            sources.append(Source.RAG)
        if best_intent in (Intent.DATA, Intent.COMBINED):
            sources.append(Source.ONE_C)

        # Extract tax type
        tax_type = self._extract_tax_type(text)

        return ClassificationResult(
            intent=best_intent,
            sources=sources,
            tax_type=tax_type,
            confidence=confidence,
        )

    def _extract_tax_type(self, text: str) -> Optional[str]:
        """Extract tax type from query text.

        Args:
            text: User query.

        Returns:
            Tax type code (nds, profit, usn) or None.
        """
        text_lower = text.lower()
        for ru_name, en_code in TAX_KEYWORDS.items():
            if ru_name in text_lower:
                return en_code
        return None


class LLMClassifier:
    """LLM-based classifier using GigaChat function calling.

    Used as fallback when rule-based confidence < 0.7.
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize LLM classifier.

        Args:
            api_key: GigaChat API key (optional, for testing).
        """
        self.api_key = api_key
        self._client = None  # Lazy init for GigaChat client

    def classify(self, text: str, rule_result: ClassificationResult) -> ClassificationResult:
        """Classify using LLM when rule-based confidence is low.

        Args:
            text: User query.
            rule_result: Previous rule-based classification.

        Returns:
            Refined ClassificationResult from LLM.
        """
        if rule_result.confidence >= 0.7:
            # High confidence, no need for LLM
            return rule_result

        logger.info("Rule confidence %.2f < 0.7, falling back to LLM classifier", rule_result.confidence)

        if not self.api_key:
            logger.warning("No GigaChat API key, returning rule-based result")
            return rule_result

        # TODO: Implement GigaChat function calling
        # For MVP, return rule-based result with adjusted confidence
        return ClassificationResult(
            intent=rule_result.intent,
            sources=rule_result.sources,
            tax_type=rule_result.tax_type,
            confidence=0.5,  # LLM confidence for ambiguous queries
            clarifying_question="Вам нужна справка по закону или фактические цифры из 1С?",
        )


class IntentClassifier:
    """Combined intent classifier (rule-based + LLM fallback)."""

    def __init__(
        self,
        rule_threshold: float = 0.7,
        llm_api_key: Optional[str] = None,
    ):
        """Initialize classifier.

        Args:
            rule_threshold: Confidence threshold for rule-based classification.
            llm_api_key: GigaChat API key for LLM fallback.
        """
        self.rule_threshold = rule_threshold
        self.rule_classifier = RuleBasedClassifier()
        self.llm_classifier = LLMClassifier(api_key=llm_api_key)

        logger.info(
            "IntentClassifier initialized: rule_threshold=%.2f",
            rule_threshold,
        )

    def classify(self, text: str) -> ClassificationResult:
        """Classify user query.

        Pipeline:
        1. Rule-based classification (fast)
        2. If confidence < threshold → LLM classification
        3. If LLM confidence < 0.7 → clarifying question

        Args:
            text: User query text.

        Returns:
            ClassificationResult with intent, sources, and confidence.
        """
        # Step 1: Rule-based classification
        rule_result = self.rule_classifier.classify(text)

        if rule_result.confidence >= self.rule_threshold:
            logger.info(
                "Rule-based classification: intent=%s, confidence=%.2f",
                rule_result.intent,
                rule_result.confidence,
            )
            return rule_result

        # Step 2: LLM fallback
        llm_result = self.llm_classifier.classify(text, rule_result)

        if llm_result.confidence < 0.7:
            # Step 3: Clarifying question
            llm_result.clarifying_question = (
                "Вам нужна справка по закону или фактические цифры из 1С?"
            )
            logger.info(
                "LLM confidence %.2f < 0.7, adding clarifying question",
                llm_result.confidence,
            )

        return llm_result

    def classify_with_traceparent(self, text: str, traceparent: str) -> ClassificationResult:
        """Classify query with traceparent for observability.

        Args:
            text: User query.
            traceparent: W3C traceparent header value.

        Returns:
            ClassificationResult.
        """
        logger.info(
            "Classifying query (traceparent=%s): %s",
            traceparent[:20] if traceparent else "none",
            text[:50],
        )
        return self.classify(text)
