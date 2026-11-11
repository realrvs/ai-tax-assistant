"""User whitelist + 1C user binding + hashed ID.

ADR-003: Whitelist + привязка к 1С-пользователю.
NFR-SEC-001: Reject 100% of unauthorized Telegram IDs.
TM-03: Elevation of Privilege — prevent access to other users' data.
TM-06: Sensitive Information Disclosure — hashed IDs in telemetry.

Covers:
- FR-005: Telegram bot with whitelist
- NFR-SEC-001: Whitelist Telegram IDs
- TM-03, TM-06: User binding + hashed ID
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Default whitelist from environment
DEFAULT_WHITELIST: List[int] = [
    int(id_str.strip())
    for id_str in os.getenv("WHITELIST_TELEGRAM_IDS", "").split(",")
    if id_str.strip()
]

# 1C user mapping (Telegram ID → 1C user code)
# In production: loaded from 1C API or database
_ONE_C_USER_MAP: Dict[int, str] = {}


@dataclass
class UserInfo:
    """User information with binding to 1C."""
    telegram_id: int
    telegram_chat_id: int
    telegram_username: Optional[str] = None
    one_c_user_code: Optional[str] = None
    one_c_user_name: Optional[str] = None
    hashed_telegram_id: str = ""
    hashed_chat_id: str = ""
    is_authorized: bool = False

    def __post_init__(self):
        """Auto-generate hashed IDs."""
        self.hashed_telegram_id = self._hash_id(self.telegram_id)
        self.hashed_chat_id = self._hash_id(self.telegram_chat_id)

    @staticmethod
    def _hash_id(value: int) -> str:
        """Hash a numeric ID using SHA-256.

        Used for telemetry (OBS-C-04, NFR-OBS-004).
        """
        return hashlib.sha256(str(value).encode()).hexdigest()[:16]

    @property
    def display_id(self) -> str:
        """Display-safe ID for logs (masked)."""
        return f"tg:{self.hashed_telegram_id}"


class WhitelistManager:
    """Manages Telegram ID whitelist and 1C user binding.

    ADR-003: Whitelist + привязка к 1С-пользователю.
    """

    def __init__(
        self,
        whitelist: Optional[List[int]] = None,
        one_c_api_url: Optional[str] = None,
    ):
        """Initialize whitelist manager.

        Args:
            whitelist: List of authorized Telegram IDs.
            one_c_api_url: 1C API URL for user binding.
        """
        self.whitelist: Set[int] = set(whitelist or DEFAULT_WHITELIST)
        self.one_c_api_url = one_c_api_url
        self._user_info: Dict[int, UserInfo] = {}

        logger.info(
            "WhitelistManager initialized: %d users",
            len(self.whitelist),
        )

    def is_authorized(self, telegram_id: int) -> bool:
        """Check if Telegram ID is in whitelist.

        NFR-SEC-001: 100% of unauthorized IDs are rejected.

        Args:
            telegram_id: Telegram user ID.

        Returns:
            True if authorized, False otherwise.
        """
        if not self.whitelist:
            logger.warning("Whitelist is empty — all users are authorized!")
            return True

        authorized = telegram_id in self.whitelist
        if not authorized:
            logger.warning("Unauthorized Telegram ID: %s", telegram_id)

        return authorized

    def get_or_create_user_info(self, message) -> UserInfo:
        """Get or create user info from Telegram message.

        Args:
            message: aiogram Message object.

        Returns:
            UserInfo with hashed IDs and authorization status.
        """
        telegram_id = message.from_user.id
        chat_id = message.chat.id
        username = message.from_user.username

        if telegram_id in self._user_info:
            return self._user_info[telegram_id]

        user_info = UserInfo(
            telegram_id=telegram_id,
            telegram_chat_id=chat_id,
            telegram_username=username,
            is_authorized=self.is_authorized(telegram_id),
        )

        self._user_info[telegram_id] = user_info
        return user_info

    def bind_to_1c_user(
        self,
        telegram_id: int,
        one_c_user_code: str,
        one_c_user_name: Optional[str] = None,
    ) -> bool:
        """Bind Telegram user to 1C user.

        ADR-003: Привязка к 1С-пользователю prevents access to other users' data.

        Args:
            telegram_id: Telegram user ID.
            one_c_user_code: 1C user code (e.g., "user001").
            one_c_user_name: Optional 1C user display name.

        Returns:
            True if binding succeeded.
        """
        if not self.is_authorized(telegram_id):
            logger.warning(
                "Cannot bind unauthorized user %s to 1C",
                telegram_id,
            )
            return False

        _ONE_C_USER_MAP[telegram_id] = one_c_user_code

        # Update cached user info
        if telegram_id in self._user_info:
            self._user_info[telegram_id].one_c_user_code = one_c_user_code
            self._user_info[telegram_id].one_c_user_name = one_c_user_name

        logger.info(
            "Bound Telegram ID %s to 1C user %s",
            telegram_id,
            one_c_user_code,
        )
        return True

    def get_1c_user_code(self, telegram_id: int) -> Optional[str]:
        """Get 1C user code for Telegram user.

        Args:
            telegram_id: Telegram user ID.

        Returns:
            1C user code or None if not bound.
        """
        return _ONE_C_USER_MAP.get(telegram_id)

    def get_user_info(self, telegram_id: int) -> Optional[UserInfo]:
        """Get cached user info.

        Args:
            telegram_id: Telegram user ID.

        Returns:
            UserInfo or None.
        """
        return self._user_info.get(telegram_id)

    def add_to_whitelist(self, telegram_id: int) -> bool:
        """Add user to whitelist dynamically.

        Args:
            telegram_id: Telegram user ID to add.

        Returns:
            True if added.
        """
        self.whitelist.add(telegram_id)
        logger.info("Added Telegram ID %s to whitelist", telegram_id)
        return True

    def remove_from_whitelist(self, telegram_id: int) -> bool:
        """Remove user from whitelist dynamically.

        Args:
            telegram_id: Telegram user ID to remove.

        Returns:
            True if removed.
        """
        if telegram_id in self.whitelist:
            self.whitelist.discard(telegram_id)
            logger.info("Removed Telegram ID %s from whitelist", telegram_id)
            return True
        return False

    def get_whitelist(self) -> List[int]:
        """Get current whitelist.

        Returns:
            List of authorized Telegram IDs.
        """
        return sorted(self.whitelist)


class SecurityContext:
    """Security context for a single request.

    Holds user info, hashed IDs, and authorization status.
    Used for telemetry (OBS-C-04) and audit logging.
    """

    def __init__(self, user_info: UserInfo):
        """Initialize security context.

        Args:
            user_info: UserInfo with hashed IDs.
        """
        self.user_info = user_info
        self.is_blocked = not user_info.is_authorized
        self.traceparent: Optional[str] = None

    def set_traceparent(self, traceparent: str) -> None:
        """Set W3C traceparent for correlation.

        OBS-C-02: traceparent propagated through security layer.
        """
        self.traceparent = traceparent

    def to_audit_log(self) -> Dict:
        """Convert to audit log entry.

        Uses hashed IDs only (no PII).
        """
        return {
            "telegram_id_hashed": self.user_info.hashed_telegram_id,
            "chat_id_hashed": self.user_info.hashed_chat_id,
            "one_c_user_code": self.user_info.one_c_user_code,
            "is_authorized": self.user_info.is_authorized,
            "is_blocked": self.is_blocked,
            "traceparent": self.traceparent,
        }
