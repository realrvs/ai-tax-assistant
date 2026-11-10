## Правила

- **Каждая задача T-XXX включает реализацию соответствующего TC-YYY из `test-specs/tax-assistant/tests.md`.** Тест пишется параллельно с кодом, не откладывается на Phase 6.
- **Phase 6 (T-501…T-506)** — это финальный прогон всех тестов, а не написание новых.
- **T-306 (OWASP LLM) и T-307 (валидация провайдера)** — финальные проверки, выполняются после завершения Phase 3 и Phase 4.
- **Docker Compose (T-507)** — опционально, Phase 7 (post-MVP). Не блокирует защиту.

## Phase 1: 1С — модель данных и HTTP-сервисы

- [ ] T-001: Создать справочник «Налоги» (Код, Наименование: НДС, Прибыль, УСН) (`src/catalogs/Taxes.xml`)
  - **FR/NFR**: FR-002
  - **Estimate**: 1
  - **Dependencies**: —

- [ ] T-002: Создать справочник «Периоды» (Год, Квартал/Месяц) (`src/catalogs/Periods.xml`)
  - **FR/NFR**: FR-002
  - **Estimate**: 1
  - **Dependencies**: —

- [ ] T-003: Создать документ «Начисление налога» (Налог, Период, Сумма) (`src/documents/TaxAccrual.xml`)
  - **FR/NFR**: FR-002
  - **ADR**: ADR-005
  - **Estimate**: 2
  - **Dependencies**: T-001, T-002

- [ ] T-004: Создать документ «Уплата налога» (Налог, Дата, Сумма) (`src/documents/TaxPayment.xml`)
  - **FR/NFR**: FR-002
  - **ADR**: ADR-005
  - **Estimate**: 2
  - **Dependencies**: T-001

- [ ] T-005: Создать регистр накопления «Сальдо ЕНС» (измерения: налог, период; ресурсы: сумма) (`config_src/AccumulationRegisters/TaxBalance.xml`)
  - **FR/NFR**: FR-002, NFR-004
  - **ADR**: ADR-005
  - **Estimate**: 3
  - **Dependencies**: T-001, T-002

- [ ] T-006: Реализовать движения документов в регистр «Сальдо ЕНС» (`src/documents/*.movements.xml`)
  - **FR/NFR**: FR-002
  - **Estimate**: 2
  - **Dependencies**: T-003, T-004, T-005

- [ ] T-007: Создать HTTP-сервис `GET /api/v1/taxes/balance` с JWT + traceparent (`src/http/TaxBalance.xml`)
  - **FR/NFR**: FR-002, NFR-004, NFR-SEC-006
  - **TM Ref**: TM-01
  - **ADR**: ADR-005
  - **Estimate**: 3
  - **Dependencies**: T-005

- [ ] T-008: Создать HTTP-сервис `POST /api/v1/taxes/calculate` с JWT + traceparent (`src/http/TaxCalculate.xml`)
  - **FR/NFR**: FR-002, NFR-SEC-006
  - **TM Ref**: TM-01
  - **ADR**: ADR-005
  - **Estimate**: 3
  - **Dependencies**: T-005

- [ ] T-009: Создать HTTP-сервис `GET /api/v1/documents/search` с JWT + traceparent (`src/http/DocumentSearch.xml`)
  - **FR/NFR**: FR-002, NFR-SEC-006
  - **TM Ref**: TM-01
  - **ADR**: ADR-005
  - **Estimate**: 2
  - **Dependencies**: T-003, T-004

- [ ] T-010: Заполнить демо-данные (3 налога, 4 периода, начисления/уплаты) (`src/data/demo.xml`)
  - **FR/NFR**: FR-002
  - **Estimate**: 1
  - **Dependencies**: T-001…T-004

## Phase 2: RAG-сервис по НК РФ

- [ ] T-101: Собрать корпус НК РФ (актуальная редакция) в машиночитаемом виде (`rag/data/nk_rf.json`)
  - **FR/NFR**: FR-001
  - **Estimate**: 3
  - **Dependencies**: —

- [ ] T-102: Реализовать чанкинг и эмбеддинги на основе Meno-Lite-0.1 (российская, RAG-оптимизированная) (`rag/embedder.py`)
  - **FR/NFR**: FR-001, NFR-006
  - **TM Ref**: TM-10
  - **ADR**: ADR-001
  - **Estimate**: 3
  - **Dependencies**: T-101

- [ ] T-103: Настроить векторную БД Chroma (persistent mode) (`rag/vector_store.py`)
  - **FR/NFR**: FR-001
  - **ADR**: ADR-002
  - **Estimate**: 2
  - **Dependencies**: T-102

- [ ] T-104: Реализовать поиск top-k с фильтрацией по статьям (`rag/search.py`)
  - **FR/NFR**: FR-001, NFR-002
  - **ADR**: ADR-002
  - **Estimate**: 3
  - **Dependencies**: T-103

- [ ] T-105: Написать тесты на точность поиска (≥ 90%) (`rag/tests/test_search.py`)
  - **FR/NFR**: FR-001, NFR-002
  - **Estimate**: 3
  - **Dependencies**: T-104

## Phase 3: Слой оркестрации и Telegram-бот

- [ ] T-201: Реализовать классификатор интентов (rule-based + GigaChat function calling) (`orchestrator/classifier.py`)
  - **FR/NFR**: FR-003
  - **TM Ref**: TM-04
  - **ADR**: ADR-001
  - **Estimate**: 5
  - **Dependencies**: —

- [ ] T-202: Реализовать синтез ответа с цитированием через GigaChat 3.5 Reasoning + валидация цитат (`orchestrator/synthesizer.py`)
  - **FR/NFR**: FR-004, NFR-SEC-003
  - **TM Ref**: TM-05, TM-07
  - **ADR**: ADR-001, ADR-002
  - **Estimate**: 5
  - **Dependencies**: T-201

- [ ] T-203: Реализовать fallback на RusMind Сокол 4.7 (Ollama) при недоступности GigaChat API (`orchestrator/fallback.py`)
  - **FR/NFR**: FR-004, NFR-006
  - **TM Ref**: TM-10
  - **ADR**: ADR-001
  - **Estimate**: 3
  - **Dependencies**: T-202

- [ ] T-204: Реализовать вызовы 1С API и RAG из оркестратора (с traceparent) (`orchestrator/sources.py`)
  - **FR/NFR**: FR-001, FR-002
  - **ADR**: ADR-005
  - **Estimate**: 3
  - **Dependencies**: T-007, T-104

- [ ] T-205: Реализовать Telegram-бота (aiogram) с middleware для traceparent (`bot/main.py`)
  - **FR/NFR**: FR-005
  - **Estimate**: 3
  - **Dependencies**: T-202

- [ ] T-206: Реализовать whitelist пользователей + привязку к 1С-пользователю + hashed ID (`bot/security.py`)
  - **FR/NFR**: FR-005, NFR-SEC-001
  - **TM Ref**: TM-03, TM-06
  - **ADR**: ADR-003
  - **Estimate**: 3
  - **Dependencies**: T-205

- [ ] T-207: Написать интеграционные тесты (вопрос → ответ) (`tests/integration/`)
  - **FR/NFR**: FR-001…FR-006
  - **Estimate**: 3
  - **Dependencies**: T-204, T-205

## Phase 4: Безопасность (LLM + данные)

- [ ] T-301: Реализовать санитизацию ввода + системный промпт + allowlist retrieved docs (`orchestrator/security.py`)
  - **FR/NFR**: NFR-SEC-002
  - **TM Ref**: TM-04
  - **Estimate**: 3
  - **Dependencies**: T-201

- [ ] T-302: Реализовать тесты prompt injection (вредоносные запросы) (`tests/security/prompt_injection.py`)
  - **FR/NFR**: NFR-SEC-002
  - **TM Ref**: TM-04
  - **Estimate**: 3
  - **Dependencies**: T-301

- [ ] T-303: Реализовать аудит запросов/ответов с ротацией 90 дней (`orchestrator/audit.py`)
  - **FR/NFR**: FR-006, NFR-SEC-004, NFR-OBS-004
  - **TM Ref**: TM-02, TM-06, TM-09
  - **ADR**: ADR-004, ADR-006
  - **Estimate**: 3
  - **Dependencies**: T-202

- [ ] T-304: Настроить HTTPS + JWT для 1С API (ротация ключей) (`deploy/security.md`)
  - **FR/NFR**: NFR-SEC-006
  - **TM Ref**: TM-01
  - **ADR**: ADR-005
  - **Estimate**: 2
  - **Dependencies**: T-007

- [ ] T-305: Реализовать rate limiting в Telegram-боте (`bot/rate_limit.py`)
  - **FR/NFR**: NFR-SEC-005
  - **TM Ref**: TM-08
  - **Estimate**: 2
  - **Dependencies**: T-205

- [ ] T-306: Прогнать OWASP Top 10 for LLM чеклист (`docs/owasp-llm.md`)
  - **FR/NFR**: NFR-SEC-002, NFR-SEC-003
  - **TM Ref**: TM-04, TM-05, TM-07
  - **Estimate**: 3
  - **Dependencies**: T-301, T-302

- [ ] T-307: Реализовать проверку провайдера LLM (GigaChat / Meno-Lite / RusMind) при старте + тест (`tests/nfr/test_llm_provider.py`)
  - **FR/NFR**: NFR-006
  - **TM Ref**: TM-10
  - **ADR**: ADR-001
  - **Estimate**: 2
  - **Dependencies**: T-202, T-203

## Phase 5: Observability (инструментирование, экспорт, dashboard, алерты)

- [ ] T-401: Подключить OpenTelemetry SDK в Orchestrator (FastAPI auto-instrumentation) (`orchestrator/telemetry.py`)
  - **FR/NFR**: NFR-OBS-001, NFR-OBS-002
  - **OBS Ref**: OBS-C-01, OBS-C-02
  - **Estimate**: 3
  - **Dependencies**: T-201

- [ ] T-402: Добавить ручные спаны для бизнес-операций (`telegram.message`, `orchestrator.classify`, `rag.search`, `1c.api.call`, `llm.synthesize`, `answer.send`) (`orchestrator/spans.py`)
  - **FR/NFR**: NFR-OBS-001, NFR-OBS-002
  - **OBS Ref**: OBS-C-01, OBS-C-02
  - **Estimate**: 5
  - **Dependencies**: T-401, T-204, T-205

- [ ] T-403: Настроить экспорт в otel-collector → loki (logs), prometheus (metrics), langfuse (traces) (`deploy/otel-config.yaml`)
  - **FR/NFR**: NFR-OBS-001
  - **OBS Ref**: OBS-C-01
  - **Estimate**: 3
  - **Dependencies**: T-401

- [ ] T-404: Настроить redaction processor в otel-collector + hashed ID в приложении (`deploy/otel-redaction.yaml`, `orchestrator/security.py`)
  - **FR/NFR**: NFR-OBS-004, NFR-SEC-004
  - **TM Ref**: TM-06, TM-09
  - **ADR**: ADR-006
  - **OBS Ref**: OBS-C-04
  - **Estimate**: 3
  - **Dependencies**: T-403, T-303

- [ ] T-405: Создать dashboard в grafana (RED-метрики + SLO + бизнес-сигналы) (`deploy/grafana-dashboard.json`)
  - **FR/NFR**: NFR-OBS-003, NFR-OBS-005
  - **OBS Ref**: OBS-C-03, OBS-C-05
  - **Estimate**: 3
  - **Dependencies**: T-403

- [ ] T-406: Настроить алерты в grafana (SLO breach: latency p95 > 10s, error rate > 1%, availability < 99%) (`deploy/grafana-alerts.yaml`)
  - **FR/NFR**: NFR-OBS-003
  - **OBS Ref**: OBS-C-03
  - **Estimate**: 2
  - **Dependencies**: T-405

## Phase 6: Тестирование и подготовка к защите

- [ ] T-501: Прогнать функциональные тесты TC-001…TC-012 (`tests/functional.md`)
  - **FR/NFR**: FR-001…FR-005, NFR-001…NFR-003
  - **Estimate**: 3
  - **Dependencies**: T-204, T-205

- [ ] T-502: Прогнать security-тесты TC-013…TC-026 + TC-OBS-006 (`tests/security.md`)
  - **FR/NFR**: NFR-SEC-001…006, NFR-006
  - **TM Ref**: TM-01…TM-10
  - **Estimate**: 3
  - **Dependencies**: T-301, T-303, T-304, T-305, T-307

- [ ] T-503: Прогнать observability-тесты TC-OBS-001…TC-OBS-005 (`tests/observability.md`)
  - **FR/NFR**: NFR-OBS-001…NFR-OBS-005
  - **OBS Ref**: OBS-C-01…OBS-C-05
  - **Estimate**: 3
  - **Dependencies**: T-404, T-405, T-406

- [ ] T-504: Подготовить демо-сценарий (3 вопроса: закон, данные, комбинированный) (`docs/demo.md`)
  - **FR/NFR**: FR-001…FR-006
  - **Estimate**: 3
  - **Dependencies**: T-501, T-502, T-503

- [ ] T-505: Подготовить слайды и ответы на вопросы жюри (`docs/slides.md`, `docs/qa.md`)
  - **FR/NFR**: FR-001…FR-006, NFR-001…NFR-006, NFR-OBS-001…NFR-OBS-005
  - **Estimate**: 3
  - **Dependencies**: T-504

- [ ] T-506: Снять резервную копию БД 1С и индекса RAG перед защитой (`backup/` — вне репозитория)
  - **FR/NFR**: NFR-004
  - **Estimate**: 1
  - **Dependencies**: T-501, T-502, T-503

## Phase 7: Post-MVP (опционально)

- [ ] T-507: Docker Compose для локального развёртывания (1С + RAG + bot + observability)
  - **FR/NFR**: NFR-004
  - **Estimate**: 5
  - **Dependencies**: T-501…T-506
  - **Note**: Опционально для MVP. 1С Docker-образ неофициальный — использовать Комьюнити-лицензию на локальной машине.
