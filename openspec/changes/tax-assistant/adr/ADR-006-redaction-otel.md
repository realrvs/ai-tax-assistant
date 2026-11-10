# ADR-006: Redaction PII в телеметрии (otel-collector)

## Статус
Accepted

## Контекст
Телеметрия (logs/spans/metrics) может содержать PII (запросы пользователей, ответы, chat_id, финансовые данные). Связано с **TM-06** (Sensitive Information Disclosure) и **TM-09** (PII in telemetry). Покрывает **NFR-OBS-004**, **NFR-SEC-004**. Связано с **OBS-C-04** (redaction by design) и **OBS-C-05** (verification).

## Решение
**Redaction processor в otel-collector** — единая точка редактирования PII до экспорта в бэкенды (loki, prometheus, langfuse). Правила:
- `telegram.chat_id`, `user_id` → hashed (SHA-256) на стороне приложения до отправки в otel-collector.
- `query`, `prompt`, `response` → редактируются в otel-collector (regex + allowlist полей) перед экспортом в langfuse.
- Все сигналы с `pii: true` (из Observability Contract) проходят через redaction processor.
- Каждое редактирование логируется как `security.pii.redacted` с `field.name`, `trace_id`.

**Точка redaction:** otel-collector (централизованно) + приложение (hashed ID до отправки). Двойная защита: приложение хеширует ID, otel-collector редактирует текстовые поля.

## Последствия

**Плюсы:**
- Единая точка redaction (otel-collector) — проще аудит.
- 0 PII в бэкендах (NFR-OBS-004, OBS-C-04).
- `security.pii.redacted` audit-лог для верификации.
- Hashed ID в приложении — дополнительная защита.

**Минусы:**
- otel-collector — дополнительный компонент (уже в стеке).
- Redaction может замедлить обработку телеметрии (незначительно).
- Regex-правила нужно поддерживать при изменении схемы сигналов.

**Риски:**
- Redaction не покрывает новое поле с PII → **Митигация:** тест TC-OBS-004 + ревью Observability Contract при изменении (T-404).
- Утечка PII до redaction (в приложении) → **Митигация:** hashed ID на стороне приложения (T-206).

**Влияние на наблюдаемость:**
- Добавлен лог `security.pii.redacted` с `field.name`, `trace_id` (OBS-C-04).
- Redaction processor в otel-collector — точка инструментирования (OBS-C-04).
- **Влияние на OBS-C-01…06:** OBS-C-04 (redaction by design), OBS-C-05 (verification в apply.md — чек-лист «0 PII в бэкендах»).

## Альтернативы
| Альтернатива | Отклонена | Причина |
|---|---|---|
| Redaction только в приложении | Да | Дублирование логики; риск пропустить поле |
| Redaction только в бэкендах (loki/prometheus/langfuse) | Да | PII уже ушла из контура; нарушает 152-ФЗ |
| Без redaction (только hashed ID) | Да | Не покрывает текстовые поля (query, response) |
| Redaction в каждом сервисе отдельно | Да | Нет единой точки аудита; сложнее поддерживать |
