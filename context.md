# Context

## Input Data (fixed)
- **feature:** AI-ассистент по налоговым вопросам
- **domain:** tax-assistant
- **constraints:** 1С (учебная/Комьюнити), российская LLM, Telegram, Python, FastAPI, Chroma
- **security_context:** regulatory=[152-ФЗ], ai=[RAG, LLM, tool-calling], assets=[financial_data, PII, secrets]
- **gost_compliance:** false

## Threat Model
- **Методология:** STRIDE + OWASP Top 10 for LLM
- **Обоснование:** ai непусто + 152-ФЗ + PII/financial_data → гибридная методология
- **Ключевые угрозы:** TM-03 (Risk 20), TM-04 (Risk 20), TM-06 (Risk 20), TM-07 (Risk 20); TM-01 (Risk 15), TM-09 (Risk 16); TM-08 (Risk 12); TM-02 (Risk 9), TM-05 (Risk 9); TM-10 (Risk 8)

## Принятые ADR
- ADR-001: Выбор российской LLM (GigaChat + Meno-Lite + RusMind) — Accepted — TM-10, NFR-006
- ADR-002: RAG с обязательным цитированием + Chroma — Accepted — TM-05, TM-07, NFR-SEC-003
- ADR-003: Whitelist + привязка к 1С-пользователю — Accepted — TM-03, TM-06, NFR-SEC-001
- ADR-004: Аудит запросов/ответов (90 дней) — Accepted — TM-02, NFR-SEC-004, NFR-OBS-004
- ADR-005: HTTP-сервисы 1С с JWT — Accepted — TM-01, NFR-SEC-006
- ADR-006: Redaction PII в телеметрии (otel-collector) — Accepted — TM-06, TM-09, NFR-OBS-004

## Согласованные endpoints
- `GET /api/v1/taxes/balance` — сальдо ЕНС
- `POST /api/v1/taxes/calculate` — расчёт налога
- `GET /api/v1/documents/search` — поиск документов

## Observability
- **Инвариант:** OBS-C-01…06 (required)
- **Стек (stack):** loki (logs), prometheus (metrics), langfuse (traces), otel-collector, grafana (visualization)
- **SLO:** latency p95 ≤ 10000ms, availability ≥ 99%, error_rate ≤ 1%, citation presence ≥ 95%, RAG precision ≥ 90%
- **Ключевые сигналы:** 23 сигнала из Observability Contract (см. spec.md)
- **Redaction policy:** hashed ID в приложении + regex-редактирование в otel-collector (ADR-006)
- **Корреляция:** W3C traceparent: Telegram-бот → Orchestrator → RAG / 1С → LLM (включая async)

## Открытые вопросы
- [ ] Источник корпуса НК РФ: официальный текст vs. парсинг с гаранта?
- [ ] Срок хранения аудит-логов: 90 дней (ADR-004) — подтвердить.
- [ ] Нужен ли архив логов перед ротацией?

## Пропущенные артефакты
- (нет)

## Traceability Matrix (FINAL)
| ID | Тип | Spec § | TM § | ADR | API | Task IDs | Test IDs | Verify | OBS-C |
|----|-----|--------|------|-----|-----|----------|----------|--------|-------|
| FR-001 | FR | spec.md#fr-001 | — | ADR-002 | — | T-101…T-105, T-204 | TC-001…TC-003 | — | — |
| FR-002 | FR | spec.md#fr-002 | — | ADR-005 | /taxes/balance, /taxes/calculate, /documents/search | T-001…T-010, T-204 | TC-004, TC-005, TC-010 | — | — |
| FR-003 | FR | spec.md#fr-003 | — | — | — | T-201 | TC-007…TC-009 | — | — |
| FR-004 | FR | spec.md#fr-004 | TM-07 | ADR-001, ADR-002 | — | T-202, T-203 | TC-006, TC-011 | — | — |
| FR-005 | FR | spec.md#fr-005 | — | ADR-003 | — | T-205, T-206 | TC-012, TC-013, TC-014 | — | — |
| FR-006 | FR | spec.md#fr-006 | TM-02 | ADR-004 | — | T-206, T-303 | TC-015, TC-022 | — | — |
| NFR-001 | NFR | spec.md#nfr-001 | — | — | — | T-103, T-501 | TC-012 | SLO p95 ≤ 10s | — |
| NFR-002 | NFR | spec.md#nfr-002 | — | ADR-002 | — | T-104, T-105 | TC-001, TC-002 | RAG precision ≥ 90% | — |
| NFR-003 | NFR | spec.md#nfr-003 | TM-07 | ADR-002 | — | T-202 | TC-011 | Citation ≥ 95% | — |
| NFR-004 | NFR | spec.md#nfr-004 | — | ADR-005 | /taxes/* | T-005, T-007, T-506 | TC-004 | Availability ≥ 99% | — |
| NFR-005 | NFR | spec.md#nfr-005 | — | — | — | T-001…T-010 | TC-019 | — | — |
| NFR-006 | NFR | spec.md#nfr-006 | TM-10 | ADR-001 | — | T-102, T-203, T-307 | TC-026 | Provider ∈ allowlist | — |
| NFR-SEC-001 | NFR-SEC | spec.md#nfr-sec-001 | TM-03, TM-06 | ADR-003 | — | T-206 | TC-013 | 100% blocked | OBS-C-04 |
| NFR-SEC-002 | NFR-SEC | spec.md#nfr-sec-002 | TM-04 | (spec) | — | T-301, T-302, T-306 | TC-016…TC-018, TC-025 | 100% blocked | — |
| NFR-SEC-003 | NFR-SEC | spec.md#nfr-sec-003 | TM-05, TM-07 | ADR-002 | — | T-202, T-306 | TC-003, TC-011, TC-020, TC-025 | 100% cited | — |
| NFR-SEC-004 | NFR-SEC | spec.md#nfr-sec-004 | TM-02 | ADR-004, ADR-006 | — | T-303, T-404 | TC-015, TC-022, TC-OBS-006 | 100% logged | OBS-C-04 |
| NFR-SEC-005 | NFR-SEC | spec.md#nfr-sec-005 | TM-08 | (spec) | — | T-305 | TC-014 | 0 over limit | — |
| NFR-SEC-006 | NFR-SEC | spec.md#nfr-sec-006 | TM-01 | ADR-005 | /taxes/* | T-007…T-009, T-304 | TC-021, TC-023, TC-024 | 100% HTTPS+JWT | — |
| NFR-OBS-001 | NFR-OBS | spec.md#nfr-obs-001 | — | ADR-001, ADR-002, ADR-005 | — | T-401, T-402, T-403 | TC-OBS-001 | Signals in backends | OBS-C-01 |
| NFR-OBS-002 | NFR-OBS | spec.md#nfr-obs-002 | — | (spec) | — | T-401, T-402 | TC-OBS-002 | traceparent propagated | OBS-C-02 |
| NFR-OBS-003 | NFR-OBS | spec.md#nfr-obs-003 | — | — | — | T-405, T-406 | TC-OBS-003 | SLO → signal | OBS-C-03 |
| NFR-OBS-004 | NFR-OBS | spec.md#nfr-obs-004 | TM-06, TM-09 | ADR-006 | — | T-303, T-404 | TC-OBS-004 | 0 PII in backends | OBS-C-04 |
| NFR-OBS-005 | NFR-OBS | spec.md#nfr-obs-005 | — | — | — | T-405, T-503 | TC-OBS-005 | Checklist in apply.md | OBS-C-05 |
| TM-01 | TM | — | threat-model.md#tm-01 | ADR-005 | /taxes/* | T-007…T-009, T-304 | TC-021, TC-023, TC-024 | — | — |
| TM-02 | TM | — | threat-model.md#tm-02 | ADR-004 | — | T-303 | TC-015, TC-022 | — | — |
| TM-03 | TM | — | threat-model.md#tm-03 | ADR-003 | — | T-206 | TC-013 | — | — |
| TM-04 | TM | — | threat-model.md#tm-04 | (spec) | — | T-301, T-302, T-306 | TC-016…TC-018, TC-025 | — | — |
| TM-05 | TM | — | threat-model.md#tm-05 | ADR-002 | — | T-202, T-306 | TC-020, TC-025 | — | — |
| TM-06 | TM | — | threat-model.md#tm-06 | ADR-003, ADR-006 | — | T-206, T-303, T-404 | TC-013, TC-017, TC-OBS-004, TC-OBS-006 | — | — |
| TM-07 | TM | — | threat-model.md#tm-07 | ADR-002 | — | T-202, T-306 | TC-003, TC-006, TC-011, TC-020, TC-025 | — | — |
| TM-08 | TM | — | threat-model.md#tm-08 | (spec) | — | T-305 | TC-014 | — | — |
| TM-09 | TM | — | threat-model.md#tm-09 | ADR-006 | — | T-303, T-404 | TC-OBS-004 | — | — |
| TM-10 | TM | — | threat-model.md#tm-10 | ADR-001 | — | T-102, T-203, T-307 | TC-026 | — | — |

## Definition of Done (Final)

- [x] Все FR покрыты ≥1 Task и ≥1 Test
- [x] Все NFR покрыты ≥1 Task, ≥1 Test и ≥1 Verify Method
- [x] Все NFR-SEC покрывают ≥1 TM-NNN и имеют Security-тест
- [x] Все TM-NNN имеют контроль и связанный NFR-SEC
- [x] Методология Threat Modeling обоснована и зафиксирована
- [x] Trust Boundaries визуализированы с цветовой кодировкой
- [x] Нет ADR без связи с design.md или TM
- [x] Нет пустых обязательных ячеек в Traceability Matrix
- [x] Матрица Task → FR/NFR/TM полностью построена
- [x] context.md актуален
- [x] Все NFR-OBS покрыты ≥1 Task, ≥1 Observability-тест и ≥1 сигналом
- [x] Observability Contract заполнен (23 сигнала)
- [x] В apply.md есть Observability Verification checklist (25 чек-пунктов)
- [x] Корреляция (traceparent / X-Request-ID) зафиксирована в API Contract
- [x] Все сигналы с PII имеют redaction-контроль, связанный с TM
- [x] OBS-C-01…06 выполнены
- [x] Каждый NFR-OBS ссылается на ≥1 OBS-C-NN
- [x] observability_context.stack заполнен до design
- [x] (gost_compliance: false) — ГОСТ-документы не требуются
