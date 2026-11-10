## Миграции

- [ ] M-001: Развернуть 1С (учебная / Комьюнити) и создать базу `TaxAssistant` (`deploy/1c-setup.md`)
  - **Связанные задачи:** T-001…T-010
  - **Rollback:** удалить базу, восстановить из `backup/1c-before-mvp.dt`

- [ ] M-002: Загрузить конфигурацию 1С (справочники, документы, регистр, HTTP-сервисы) (`deploy/load-config.md`)
  - **Связанные задачи:** T-001…T-009
  - **Rollback:** восстановить предыдущую конфигурацию из `backup/config-before-mvp.cf`

- [ ] M-003: Заполнить демо-данные (3 налога, 4 периода, начисления/уплаты) (`deploy/load-demo-data.md`)
  - **Связанные задачи:** T-010
  - **Rollback:** удалить демо-записи по префиксу `DEMO-`

- [ ] M-004: Развернуть RAG-сервис (Python + Chroma + Meno-Lite) (`deploy/rag-setup.md`)
  - **Связанные задачи:** T-101…T-105
  - **Rollback:** остановить контейнер, откатить образ, восстановить индекс из `backup/rag-index/`

- [ ] M-005: Развернуть Orchestrator (FastAPI) + Telegram-бот (aiogram) (`deploy/bot-setup.md`)
  - **Связанные задачи:** T-201…T-207
  - **Rollback:** остановить бота, откатить версию, вернуть предыдущий whitelist

- [ ] M-006: Развернуть стек наблюдаемости (otel-collector → loki / prometheus / langfuse → grafana) (`deploy/observability-setup.md`)
  - **Связанные задачи:** T-401…T-406
  - **Rollback:** остановить otel-collector, откатить конфиг, вернуть предыдущие dashboard/алерты

- [ ] M-007: Настроить whitelist + привязку к 1С-пользователю + redaction (`deploy/security.md`)
  - **Связанные задачи:** T-206, T-303, T-404
  - **Rollback:** снять whitelist, отключить redaction processor

## Feature Flags

| Flag | Default | TTL | Связанный FR | Связанный TM |
|---|---|---|---|---|
| `FF_RAG_SEARCH` | ON | до защиты | FR-001 | — |
| `FF_1C_DATA` | ON | до защиты | FR-002 | — |
| `FF_LLM_SYNTHESIS` | ON | до защиты | FR-004 | — |
| `FF_LLM_FALLBACK` | ON | бессрочно | FR-004, NFR-006 | TM-10 |
| `FF_PROMPT_INJECTION_GUARD` | ON | **бессрочно** | NFR-SEC-002 | TM-04 |
| `FF_CITATION_REQUIRED` | ON | **бессрочно** | NFR-SEC-003 | TM-05, TM-07 |
| `FF_AUDIT` | ON | **бессрочно** | FR-006, NFR-SEC-004 | TM-02 |
| `FF_RATE_LIMIT` | ON | **бессрочно** | NFR-SEC-005 | TM-08 |
| `FF_REDACTION` | ON | **бессрочно** | NFR-OBS-004 | TM-06, TM-09 |
| `FF_TRACEPARENT_PROPAGATION` | ON | **бессрочно** | NFR-OBS-002 | — |
| `FF_SLO_ALERTS` | ON | **бессрочно** | NFR-OBS-003 | — |

> **Security-флаги** (`FF_PROMPT_INJECTION_GUARD`, `FF_CITATION_REQUIRED`, `FF_AUDIT`, `FF_RATE_LIMIT`, `FF_REDACTION`) **не отключаются** — покрывают TM-02, TM-04, TM-05, TM-06, TM-07, TM-08, TM-09.
>
> **Observability-флаги** (`FF_TRACEPARENT_PROPAGATION`, `FF_SLO_ALERTS`) **не отключаются** — покрывают OBS-C-02, OBS-C-03.

## Canary Deployment

1. **Deploy canary 5% трафика.**
   - Маршрутизация: 5% пользователей whitelist → canary-версия Orchestrator + бот.
   - Метрика: `telegram.messages.total{status="allowed"}` split 95/5.

2. **Monitor SLO canary vs baseline (24h):**
   - `p95 latency` ≤ **10 000 ms** (NFR-001) — измеряется по `http.server.request.duration` p95.
   - `error rate` ≤ **1%** — измеряется по `http.server.requests{status_code=5xx}`.
   - `business KPI`: `answer.citation.present.total{present="true"}` / total ≥ **95%** (NFR-003).
   - `availability` ≥ **99%** (NFR-004) — измеряется по `1c.api.duration{status_code=2xx}` / total.
   - `rag precision` ≥ **90%** (NFR-002) — офлайн на эталонном наборе.

3. **Auto-rollback при degradation > 10% по любому SLO:**
   - **Trigger:** alert в `grafana` fires (`FF_SLO_ALERTS=ON`).
   - **Action:** feature flag toggle → ротация pods → rollback deployment.
   - **Метрики для trigger:**
     - `http.server.request.duration` p95 > 11 000 ms (> 10% от 10 000).
     - `http.server.requests{status_code=5xx}` rate > 1.1% (> 10% от 1%).
     - `answer.citation.present.total{present="true"}` rate < 85.5% (> 10% от 95%).
     - `1c.api.duration{status_code=2xx}` rate < 89.1% (> 10% от 99%).

4. **Если canary stable 24h → 50% → 100%.**
   - Переключение через feature flag `FF_CANARY_ROLLOUT` (0.5 → 1.0).

5. **Отключить feature flag для old code path.**
   - После 100% стабильности 48h — удалить старый code path.

## Observability Verification

> Проверка, что сигналы из Observability Contract реально видны в **выбранных** бэкендах (`observability_context.stack`). Покрывает **OBS-C-05** и **NFR-OBS-005**.

### Logs (loki)

- [ ] В `loki` есть `telegram.request.received` с `user_id` (hashed), `chat_id` (hashed), `trace_id` для тестового запроса (OBS-C-01, OBS-C-02)
- [ ] В `loki` есть `orchestrator.classified` с `intent`, `sources`, `confidence`, `trace_id` (OBS-C-01)
- [ ] В `loki` есть `rag.search.completed` с `top_k`, `result.count`, `trace_id` (OBS-C-01)
- [ ] В `loki` есть `1c.api.called` с `endpoint`, `status_code`, `duration_ms`, `trace_id` (OBS-C-01)
- [ ] В `loki` есть `llm.request.completed` с `llm.model`, `tokens.in`, `tokens.out`, `trace_id` (OBS-C-01)
- [ ] В `loki` есть `answer.sent` с `chat_id` (hashed), `citation.present`, `trace_id` (OBS-C-01)
- [ ] В `loki` есть `security.pii.redacted` с `field.name`, `trace_id` при редактировании PII (OBS-C-04)
- [ ] В `loki` есть `security.blocked` с `reason`, `user_id` (hashed), `trace_id` при блокировке (OBS-C-01)
- [ ] В `loki` есть `audit.entry` с `user_id`, `sources`, `answer.length`, `trace_id` (OBS-C-01, OBS-C-04)

### Metrics (prometheus)

- [ ] В `prometheus` виден `http.server.request.duration` (histogram) с `http.method`, `http.route`, `http.status_code` (OBS-C-01, OBS-C-03)
- [ ] В `prometheus` виден `telegram.messages.total` с `chat.type`, `status` (OBS-C-01)
- [ ] В `prometheus` виден `rag.search.duration` с `top_k`, `result.count` (OBS-C-01)
- [ ] В `prometheus` виден `1c.api.duration` с `endpoint`, `status_code` (OBS-C-01)
- [ ] В `prometheus` виден `llm.request.duration` с `llm.model`, `llm.provider` (OBS-C-01)
- [ ] В `prometheus` виден `answer.citation.present.total` с `present`, `tax.type` (OBS-C-01, OBS-C-03)
- [ ] В `prometheus` виден `tax.question.answered` (business signal) с `tax.type`, `sources.used`, `citation.present` (OBS-C-01)
- [ ] В `prometheus` виден `1c.data.freshness` (business gauge) с `tax.type`, `as_of_date` (OBS-C-01)

### Traces (langfuse)

- [ ] В `langfuse` виден span `telegram.message` с `telegram.chat_id` (hashed), `trace_id` (OBS-C-01, OBS-C-02)
- [ ] В `langfuse` виден span `orchestrator.classify` с `intent`, `sources.selected`, `confidence`, `trace_id` (OBS-C-01)
- [ ] В `langfuse` виден span `rag.search` с `query.length`, `top_k`, `result.count`, `trace_id` (OBS-C-01)
- [ ] В `langfuse` виден span `1c.api.call` с `endpoint`, `status_code`, `duration_ms`, `trace_id` (OBS-C-01)
- [ ] В `langfuse` виден span `llm.synthesize` с `llm.model`, `tokens.in`, `tokens.out`, `citation.present`, `trace_id` (OBS-C-01, OBS-C-02)
- [ ] В `langfuse` виден span `answer.send` с `chat_id` (hashed), `answer.length`, `trace_id` (OBS-C-01)
- [ ] В `langfuse` **один** `trace_id` связывает все спаны для тестового запроса (OBS-C-02)
- [ ] В `langfuse` **нет PII** в `query`, `prompt`, `response` (OBS-C-04)

### Correlation (OBS-C-02)

- [ ] `traceparent` из Telegram-бота присутствует в спане `llm.synthesize` (OBS-C-02)
- [ ] `traceparent` из Telegram-бота присутствует в спане `1c.api.call` (OBS-C-02)
- [ ] `trace_id` присутствует в `ErrorResponse` для 4xx/5xx (OBS-C-02, api-contract)
- [ ] `trace_id` присутствует в каждом логе (`telegram.request.received`, `orchestrator.classified`, `rag.search.completed`, `1c.api.called`, `llm.request.completed`, `answer.sent`) (OBS-C-02)

### Alerts & Dashboard (grafana)

- [ ] В `grafana` виден dashboard с RED-метриками для фичи (OBS-C-05)
- [ ] В `grafana` виден dashboard с SLO (latency p95, availability, error_rate, citation presence) (OBS-C-03)
- [ ] В `grafana` виден dashboard с бизнес-сигналами (`tax.question.answered`, `1c.data.freshness`) (OBS-C-01)
- [ ] Алерт `SLO_LATENCY_BREACH` срабатывает на тестовом сценарии (p95 > 10 000 ms) (OBS-C-03)
- [ ] Алерт `SLO_ERROR_RATE_BREACH` срабатывает на тестовом сценарии (> 1%) (OBS-C-03)
- [ ] Алерт `SLO_AVAILABILITY_BREACH` срабатывает на тестовом сценарии (< 99%) (OBS-C-03)

### Redaction (OBS-C-04)

- [ ] `security.pii.redacted` audit-лог фиксируется при redaction в `loki` (OBS-C-04)
- [ ] В `loki`, `prometheus`, `langfuse` **0 PII** после тестового запроса с PII (OBS-C-04)
- [ ] `chat_id`, `user_id` hashed (SHA-256) в логах и спанах (OBS-C-04)
- [ ] Retention policy для `audit.entry` = 90 дней (ADR-004, NFR-SEC-004)
- [ ] Ротация логов работает (TC-OBS-006) — записи старше 90 дней удаляются (OBS-C-04)

## Rollback Plan

1. **Откат бота:** остановить контейнер, вернуть предыдущий образ (`bot:previous`).
2. **Откат RAG:** остановить контейнер, вернуть предыдущий образ + индекс из `backup/rag-index/`.
3. **Откат 1С:** восстановить конфигурацию (`backup/config-before-mvp.cf`) и БД (`backup/1c-before-mvp.dt`).
4. **Откат feature flags:** выключить `FF_RAG_SEARCH`, `FF_1C_DATA`, `FF_LLM_SYNTHESIS`, `FF_LLM_FALLBACK`; **security-флаги оставить `ON`** (`FF_PROMPT_INJECTION_GUARD`, `FF_CITATION_REQUIRED`, `FF_AUDIT`, `FF_RATE_LIMIT`, `FF_REDACTION`); **observability-флаги оставить `ON`** (`FF_TRACEPARENT_PROPAGATION`, `FF_SLO_ALERTS`).
5. **Откат observability:** остановить otel-collector, вернуть предыдущий конфиг, вернуть предыдущие dashboard/алерты из `backup/grafana/`.
6. **Проверка после отката:**
   - Прогнать TC-001 (базовый RAG) — ответ получен.
   - Прогнать TC-006 (комбинированный) — ответ с цитатой и цифрой.
   - Прогнать TC-OBS-002 (корреляция) — `trace_id` propagated.
   - Прогнать TC-OBS-004 (redaction) — 0 PII в бэкендах.
