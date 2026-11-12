"""Audit logging for all requests/responses with 90-day rotation.

FR-006: Log all queries and answers for audit transparency.
NFR-SEC-004: 100% of requests/responses logged with user binding.
NFR-OBS-004: Redaction by design (hashed IDs only).
TM-02: Repudiation protection.
TM-06, TM-09: PII in telemetry protection.
ADR-004: 90-day audit log retention.
ADR-006: Redaction PII in telemetry.

Covers:
- Audit entry creation with hashed IDs
- 90-day rotation (delete old entries)
- Optional archival via ARCHIVE_AUDIT_LOGS flag
- JSONL format for efficient appending
"""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Audit log configuration
AUDIT_LOG_DIR = Path(os.getenv("AUDIT_LOG_DIR", "data/audit"))
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.jsonl"
RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "90"))
ARCHIVE_AUDIT_LOGS = os.getenv("ARCHIVE_AUDIT_LOGS", "false").lower() == "true"
ARCHIVE_DIR = AUDIT_LOG_DIR / "archive"


class AuditEntry:
    """Audit log entry with hashed IDs only (no PII)."""

    def __init__(
        self,
        user_id_hashed: str,
        query: str,
        sources: List[str],
        answer: str,
        citations: List[str],
        trace_id: str,
        intent: str = "",
        tax_type: str = "",
        one_c_available: bool = True,
        citation_valid: bool = True,
        latency_ms: int = 0,
    ):
        """Initialize audit entry.

        Args:
            user_id_hashed: Hashed Telegram user ID (SHA-256, first 16 chars).
            query: User query text.
            sources: List of sources used (rag, 1c).
            answer: Generated answer.
            citations: List of citations (ст. XXX п. Y НК РФ).
            trace_id: W3C trace_id for correlation.
            intent: Classified intent (explain, data, combined).
            tax_type: Tax type (nds, profit, usn).
            one_c_available: Whether 1C was available.
            citation_valid: Whether citation validation passed.
            latency_ms: Response latency in milliseconds.
        """
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.user_id_hashed = user_id_hashed
        self.query = query
        self.sources = sources
        self.answer = answer
        self.answer_length = len(answer)
        self.citations = citations
        self.trace_id = trace_id
        self.intent = intent
        self.tax_type = tax_type
        self.one_c_available = one_c_available
        self.citation_valid = citation_valid
        self.latency_ms = latency_ms

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "user_id_hashed": self.user_id_hashed,
            "query": self.query,
            "sources": self.sources,
            "answer_length": self.answer_length,
            "citations": self.citations,
            "trace_id": self.trace_id,
            "intent": self.intent,
            "tax_type": self.tax_type,
            "one_c_available": self.one_c_available,
            "citation_valid": self.citation_valid,
            "latency_ms": self.latency_ms,
        }

    def to_json(self) -> str:
        """Serialize to JSONL line."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class AuditLogger:
    """Audit logger with 90-day rotation and optional archival.

    ADR-004: 90-day retention, JSONL format, admin-only access.
    ADR-006: Hashed IDs only, no PII in logs.
    """

    def __init__(
        self,
        log_file: Path = AUDIT_LOG_FILE,
        retention_days: int = RETENTION_DAYS,
        archive_enabled: bool = ARCHIVE_AUDIT_LOGS,
    ):
        """Initialize audit logger.

        Args:
            log_file: Path to audit log file.
            retention_days: Number of days to retain logs.
            archive_enabled: Whether to archive before deletion.
        """
        self.log_file = log_file
        self.retention_days = retention_days
        self.archive_enabled = archive_enabled

        # Ensure directories exist
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if archive_enabled:
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(
            "AuditLogger initialized: retention=%d days, archive=%s",
            retention_days,
            archive_enabled,
        )

    def log(
        self,
        user_id_hashed: str,
        query: str,
        sources: List[str],
        answer: str,
        citations: List[str],
        trace_id: str,
        intent: str = "",
        tax_type: str = "",
        one_c_available: bool = True,
        citation_valid: bool = True,
        latency_ms: int = 0,
    ) -> None:
        """Log an audit entry.

        FR-006: Log all queries and answers.
        NFR-SEC-004: 100% of requests/responses logged.

        Args:
            user_id_hashed: Hashed user ID.
            query: User query.
            sources: Sources used.
            answer: Generated answer.
            citations: Citations in answer.
            trace_id: Trace ID for correlation.
            intent: Classified intent.
            tax_type: Tax type.
            one_c_available: Whether 1C was available.
            citation_valid: Whether citation validation passed.
            latency_ms: Response latency.
        """
        entry = AuditEntry(
            user_id_hashed=user_id_hashed,
            query=query,
            sources=sources,
            answer=answer,
            citations=citations,
            trace_id=trace_id,
            intent=intent,
            tax_type=tax_type,
            one_c_available=one_c_available,
            citation_valid=citation_valid,
            latency_ms=latency_ms,
        )

        # Append to JSONL file
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")

        logger.info(
            "Audit logged: user=%s, intent=%s, sources=%s, citations=%d, latency=%dms",
            user_id_hashed[:8],
            intent,
            sources,
            len(citations),
            latency_ms,
        )

    def rotate(self) -> int:
        """Rotate audit logs older than retention period.

        ADR-004: Delete entries older than 90 days.
        Optional archival via ARCHIVE_AUDIT_LOGS flag.

        Returns:
            Number of entries archived/deleted.
        """
        if not self.log_file.exists():
            return 0

        # Read all entries
        entries = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)

        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry_dict = json.loads(line)
                    entry_date = datetime.fromisoformat(entry_dict["timestamp"])

                    if entry_date < cutoff_date:
                        # Entry is older than retention period
                        if self.archive_enabled:
                            self._archive_entry(entry_dict)
                        # Entry is deleted (not added to entries list)
                    else:
                        entries.append(line)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Invalid audit entry: %s", e)

        # Rewrite log file with only recent entries
        with open(self.log_file, "w", encoding="utf-8") as f:
            for line in entries:
                f.write(line + "\n")

        archived_count = len(entries) - sum(1 for _ in open(self.log_file))
        logger.info(
            "Audit rotation complete: %d entries kept, cutoff=%s",
            len(entries),
            cutoff_date.date(),
        )

        return archived_count

    def _archive_entry(self, entry_dict: Dict[str, Any]) -> None:
        """Archive an entry before deletion.

        Args:
            entry_dict: Entry dictionary to archive.
        """
        archive_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        archive_file = ARCHIVE_DIR / f"audit_{archive_date}.jsonl"

        with open(archive_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry_dict, ensure_ascii=False) + "\n")

        logger.info("Archived audit entry to %s", archive_file)

    def get_entries(
        self,
        user_id_hashed: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit entries.

        Admin-only access for debugging and compliance.

        Args:
            user_id_hashed: Filter by hashed user ID.
            from_date: Filter from date (ISO format).
            to_date: Filter to date (ISO format).
            limit: Maximum number of entries.

        Returns:
            List of audit entry dictionaries.
        """
        if not self.log_file.exists():
            return []

        entries = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)

                    # Apply filters
                    if user_id_hashed and entry.get("user_id_hashed") != user_id_hashed:
                        continue
                    if from_date and entry.get("timestamp", "") < from_date:
                        continue
                    if to_date and entry.get("timestamp", "") > to_date:
                        continue

                    entries.append(entry)

                    if len(entries) >= limit:
                        break
                except json.JSONDecodeError:
                    continue

        return entries

    def get_entry_count(self) -> int:
        """Get total number of entries in audit log."""
        if not self.log_file.exists():
            return 0

        count = 0
        with open(self.log_file, "r", encoding="utf-8") as f:
            for _ in f:
                count += 1

        return count

    def clear_all(self) -> int:
        """Clear all audit entries. Admin-only operation.

        Returns:
            Number of entries cleared.
        """
        if not self.log_file.exists():
            return 0

        count = self.get_entry_count()
        self.log_file.unlink()

        logger.warning("Cleared all %d audit entries", count)
        return count


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create global audit logger instance.

    Returns:
        AuditLogger singleton.
        """
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def log_audit_entry(**kwargs) -> None:
    """Convenience function to log an audit entry.

    Args:
        **kwargs: AuditEntry fields.
    """
    logger = get_audit_logger()
    logger.log(**kwargs)
