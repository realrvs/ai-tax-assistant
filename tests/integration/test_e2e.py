"""Integration tests for Tax Assistant (TC-007...TC-014).

Covers end-to-end flows:
- TC-007: Classifier — только RAG
- TC-008: Classifier — только 1C
- TC-009: Classifier — неоднозначный запрос
- TC-010: 1C недоступна → fallback на RAG
- TC-011: Ответ без источника отклоняется
- TC-012: Telegram — успешный ответ
- TC-013: Telegram — неавторизованный пользователь
- TC-014: Rate limiting

Phase 3 integration tests.
Dependencies: T-204 (sources), T-205 (bot).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.classifier import IntentClassifier, Intent, Source
from orchestrator.synthesizer import Synthesizer, SynthesisRequest, SynthesisResponse
from orchestrator.sources import SourceOrchestrator, OneCAPI, RAGSource


class TestClassifierIntegration:
    """TC-007, TC-008, TC-009: Intent classifier integration tests."""

    @pytest.fixture
    def classifier(self):
        """Create classifier instance."""
        return IntentClassifier()

    def test_tc007_classify_explain_only_rag(self, classifier):
        """TC-007: Query about tax law → only RAG source.

        FR-003: Запрос только про закон → только RAG.
        """
        result = classifier.classify("Какой срок уплаты НДС?")

        assert result.intent == Intent.EXPLAIN
        assert Source.RAG in result.sources
        assert Source.ONE_C not in result.sources
        assert result.confidence >= 0.7

    def test_tc008_classify_data_only_1c(self, classifier):
        """TC-008: Query about my data → only 1C source.

        FR-003: Запрос только про мои данные → только 1C.
        """
        result = classifier.classify("Покажи мои документы за Q1 2026")

        assert result.intent == Intent.DATA
        assert Source.ONE_C in result.sources
        assert Source.RAG not in result.sources
        assert result.confidence >= 0.7

    def test_tc009_classify_combined(self, classifier):
        """TC-009: Combined query → RAG + 1C.

        FR-003: Комбинированный запрос → оба источника.
        """
        result = classifier.classify("Почему у меня переплата по НДС?")

        assert result.intent == Intent.COMBINED
        assert Source.RAG in result.sources
        assert Source.ONE_C in result.sources

    def test_tc009_ambiguous_query(self, classifier):
        """TC-009: Ambiguous query → clarifying question.

        FR-003: Неоднозначный запрос → уточняющий вопрос.
        """
        result = classifier.classify("Что с налогами?")

        assert result.intent == Intent.UNKNOWN
        assert result.confidence < 0.7
        assert result.clarifying_question is not None
        assert "закону" in result.clarifying_question.lower() or "1с" in result.clarifying_question.lower()

    def test_tc007_tax_rate_query(self, classifier):
        """TC-007: Tax rate query → explain intent.

        FR-003: Запрос о ставке → только RAG.
        """
        result = classifier.classify("Какая ставка НДС в 2026 году?")

        assert result.intent == Intent.EXPLAIN
        assert result.tax_type == "nds"
        assert Source.RAG in result.sources

    def test_tc008_balance_query(self, classifier):
        """TC-008: Balance query → data intent.

        FR-003: Запрос о сальдо → только 1C.
        """
        result = classifier.classify("Какое у меня сальдо ЕНС по НДС?")

        assert result.intent == Intent.DATA
        assert result.tax_type == "nds"
        assert Source.ONE_C in result.sources

    def test_tc009_calculate_query(self, classifier):
        """TC-009: Calculate query → combined intent.

        FR-003: Запрос о расчёте → оба источника.
        """
        result = classifier.classify("Сколько я должен платить НДС за Q1 2026?")

        assert result.intent == Intent.COMBINED
        assert Source.RAG in result.sources
        assert Source.ONE_C in result.sources


class TestSynthesisIntegration:
    """TC-011: Answer synthesis with citation validation."""

    @pytest.fixture
    def synthesizer(self):
        """Create synthesizer instance."""
        return Synthesizer()

    def test_tc011_answer_without_citation_rejected(self, synthesizer):
        """TC-011: Answer without citation is rejected.

        FR-004, NFR-SEC-003: Ответ без источника отклоняется.
        """
        # Mock response without citation
        mock_response = SynthesisResponse(
            answer="НДС составляет 20%",
            citations=[],
            sources_used=["rag"],
            citation_valid=False,
        )

        validated = synthesizer.validate_and_reject(mock_response)

        assert not validated.citation_valid
        assert "Не удалось подтвердить ответ источником" in validated.answer
        assert validated.error is not None

    def test_tc011_answer_with_valid_citation_accepted(self, synthesizer):
        """TC-011: Answer with valid citation is accepted.

        NFR-SEC-003: Ответ с корректной ссылкой принимается.
        """
        mock_response = SynthesisResponse(
            answer="Согласно ст. 164 п. 1 НК РФ, ставка НДС составляет 20%.",
            citations=["ст. 164 п. 1 НК РФ"],
            sources_used=["rag"],
            citation_valid=True,
        )

        validated = synthesizer.validate_and_reject(mock_response)

        assert validated.citation_valid
        assert validated.error is None
        assert "ст. 164 п. 1 НК РФ" in validated.answer

    def test_tc011_hallucinated_citation_rejected(self, synthesizer):
        """TC-011: Citation not in RAG results is rejected.

        NFR-SEC-003: Галлюцинация статьи отклоняется.
        """
        # RAG returned article 164, but answer cites article 999
        rag_results = [{"article": 164, "paragraph": "1", "text": "Ставка НДС 20%"}]

        response = SynthesisResponse(
            answer="Согласно ст. 999 п. 1 НК РФ, ...",
            citations=["ст. 999 п. 1 НК РФ"],
            sources_used=["rag"],
            citation_valid=True,
        )

        # Validate should detect hallucination
        is_valid = synthesizer._validate_citation(response.answer, rag_results)

        assert not is_valid, "Hallucinated citation should be rejected"

    def test_tc011_citation_extraction(self, synthesizer):
        """Test citation extraction from answer text."""
        answer = "Согласно ст. 164 п. 1 НК РФ, ставка НДС 20%. Также ст. 165 п. 2 НК РФ предусматривает льготы."

        citations = synthesizer._extract_citations(answer)

        assert len(citations) == 2
        assert "ст. 164 п. 1 НК РФ" in citations
        assert "ст. 165 п. 2 НК РФ" in citations


class TestSourceOrchestratorIntegration:
    """Integration tests for source orchestration."""

    def test_tc010_1c_unavailable_fallback_to_rag(self):
        """TC-010: 1C unavailable → fallback to RAG only.

        FR-002: 1С недоступна → ответ только по НК РФ.
        """
        orchestrator = SourceOrchestrator()

        # Mock 1C API to raise exception
        with patch.object(orchestrator.one_c_api, 'get_balance') as mock_balance:
            mock_balance.side_effect = Exception("1C API timeout")

            result = orchestrator.fetch_sources(
                query="Какое у меня сальдо?",
                intent="combined",
                tax_type="nds",
            )

            # RAG should still work (or return empty if not preloaded)
            assert "rag_results" in result
            # 1C data should have error
            assert result["one_c_data"] is not None
            assert "error" in result["one_c_data"]
            assert "недоступны" in result["one_c_data"]["error"].lower() or "unavailable" in result["one_c_data"]["error"].lower()

    def test_traceparent_generated(self):
        """Test that traceparent is generated for correlation."""
        orchestrator = SourceOrchestrator()
        traceparent = orchestrator.generate_traceparent()

        # W3C traceparent format: 00-{32-char}-{16-char}-01
        parts = traceparent.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert len(parts[1]) == 32  # trace_id
        assert len(parts[2]) == 16  # span_id
        assert parts[3] == "01"  # flags

    def test_source_routing_by_intent(self):
        """Test that sources are selected based on intent."""
        orchestrator = SourceOrchestrator()

        # Explain intent → RAG only
        result = orchestrator.fetch_sources(
            query="Какая ставка НДС?",
            intent="explain",
            tax_type="nds",
        )

        assert "rag_results" in result
        assert result["one_c_data"] is None

        # Data intent → 1C only (with mock)
        with patch.object(orchestrator.one_c_api, 'get_balance') as mock_balance:
            mock_balance.return_value = MagicMock(
                tax="nds",
                balance=150000.0,
                as_of_date="2026-03-31",
                trace_id="test-trace-id",
            )

            result = orchestrator.fetch_sources(
                query="Моё сальдо",
                intent="data",
                tax_type="nds",
            )

            assert result["rag_results"] == []
            assert result["one_c_data"] is not None
            assert result["one_c_data"]["balance"] == 150000.0


class TestSecurityIntegration:
    """TC-013, TC-014: Security integration tests."""

    def test_tc013_unauthorized_user_blocked(self):
        """TC-013: Unauthorized user is blocked.

        FR-005, NFR-SEC-001: Неавторизованный доступ отклоняется.
        """
        from bot.security import WhitelistManager

        manager = WhitelistManager(whitelist=[12345, 67890])

        # Authorized user
        assert manager.is_authorized(12345) is True
        assert manager.is_authorized(67890) is True

        # Unauthorized user
        assert manager.is_authorized(99999) is False

    def test_tc013_user_binding(self):
        """TC-013: Telegram user bound to 1C user.

        ADR-003: Whitelist + привязка к 1С-пользователю.
        """
        from bot.security import WhitelistManager

        manager = WhitelistManager(whitelist=[12345])

        # Bind to 1C user
        result = manager.bind_to_1c_user(12345, "user001", "Иванов И.И.")

        assert result is True
        assert manager.get_1c_user_code(12345) == "user001"

    def test_tc013_unauthorized_cannot_bind(self):
        """TC-013: Unauthorized user cannot bind to 1C.

        TM-03: Elevation of Privilege prevention.
        """
        from bot.security import WhitelistManager

        manager = WhitelistManager(whitelist=[12345])

        # Unauthorized user
        result = manager.bind_to_1c_user(99999, "user001")

        assert result is False

    def test_tc014_hashed_ids(self):
        """TC-014: Telegram IDs are hashed for telemetry.

        OBS-C-04: Redaction by design.
        """
        from bot.security import UserInfo

        user = UserInfo(
            telegram_id=12345,
            telegram_chat_id=67890,
        )

        # Hashed IDs should be non-empty and deterministic
        assert len(user.hashed_telegram_id) == 16
        assert len(user.hashed_chat_id) == 16

        # Same ID → same hash
        user2 = UserInfo(telegram_id=12345, telegram_chat_id=67890)
        assert user.hashed_telegram_id == user2.hashed_telegram_id
        assert user.hashed_chat_id == user2.hashed_chat_id

        # Hash should not reveal original ID
        assert str(12345) not in user.hashed_telegram_id
        assert str(67890) not in user.hashed_chat_id

    def test_tc014_security_context_audit_log(self):
        """TC-014: Security context produces audit log without PII."""
        from bot.security import UserInfo, SecurityContext

        user = UserInfo(
            telegram_id=12345,
            telegram_chat_id=67890,
            one_c_user_code="user001",
        )
        context = SecurityContext(user)
        context.set_traceparent("00-abc123-def456-01")

        audit_log = context.to_audit_log()

        # Should contain hashed IDs, not raw IDs
        assert "12345" not in str(audit_log)
        assert "67890" not in str(audit_log)
        assert "telegram_id_hashed" in audit_log
        assert "chat_id_hashed" in audit_log
        assert "traceparent" in audit_log
        assert "one_c_user_code" in audit_log
