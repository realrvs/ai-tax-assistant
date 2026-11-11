"""Telegram bot for Tax Assistant with aiogram.

FR-005: Telegram interface with text queries and commands.
design.md: traceparent generated at bot level, propagated to Orchestrator.
NFR-001: Response latency p95 ≤ 10s.
NFR-SEC-001: Whitelist Telegram IDs.

Covers:
- FR-005: Telegram bot interface
- OBS-C-02: traceparent propagated from bot to Orchestrator
- NFR-SEC-001: Whitelist check before processing
"""

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.middleware import MiddlewareHandler
from aiogram.types import Message
from aiogram.utils.token import TokenValidationError, check_token

logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.classifier import IntentClassifier, ClassificationResult, Intent
from orchestrator.synthesizer import Synthesizer, SynthesisRequest
from orchestrator.sources import SourceOrchestrator

# Environment configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WHITELIST_IDS = [
    int(id_str.strip())
    for id_str in os.getenv("WHITELIST_TELEGRAM_IDS", "").split(",")
    if id_str.strip()
]
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

# Rate limiting config
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds


class TraceparentMiddleware(MiddlewareHandler):
    """Middleware to generate and inject traceparent for each message.

    Generates W3C traceparent: 00-{trace_id}-{span_id}-01
    Propagates to Orchestrator via HTTP header.
    """

    async def on_process_message(self, message: Message, data: Dict):
        """Generate traceparent and store in message context."""
        trace_id = uuid4().hex[:32]
        span_id = uuid4().hex[:16]
        traceparent = f"00-{trace_id}-{span_id}-01"

        # Store in message for downstream handlers
        message._ctx = {"traceparent": traceparent, "trace_id": trace_id}  # noqa: SLF001
        data["traceparent"] = traceparent
        data["trace_id"] = trace_id

        logger.info("Generated traceparent=%s for message from user %s", traceparent[:20], message.from_user.id)


class WhitelistMiddleware(MiddlewareHandler):
    """Middleware to check Telegram ID against whitelist.

    NFR-SEC-001: Reject 100% of unauthorized Telegram IDs.
    """

    async def on_process_message(self, message: Message, data: Dict):
        """Check if user is in whitelist."""
        user_id = message.from_user.id

        if WHITELIST_IDS and user_id not in WHITELIST_IDS:
            logger.warning("Unauthorized Telegram ID: %s", user_id)
            await message.answer(
                "Доступ ограничен. Для получения доступа обратитесь к администратору."
            )
            data["blocked"] = True
            return

        data["blocked"] = False


class RateLimitMiddleware(MiddlewareHandler):
    """Rate limiting middleware (≤ 10 requests/min per user).

    NFR-SEC-005: Rate limiting.
    """

    def __init__(self):
        self._requests: Dict[int, list] = {}

    def _is_rate_limited(self, user_id: int) -> bool:
        """Check if user exceeded rate limit."""
        now = __import__("time").time()

        # Clean old requests
        if user_id not in self._requests:
            self._requests[user_id] = []

        self._requests[user_id] = [
            t for t in self._requests[user_id] if now - t < RATE_LIMIT_WINDOW
        ]

        if len(self._requests[user_id]) >= RATE_LIMIT_REQUESTS:
            return True

        self._requests[user_id].append(now)
        return False

    async def on_process_message(self, message: Message, data: Dict):
        """Check rate limit before processing."""
        user_id = message.from_user.id

        if self._is_rate_limited(user_id):
            logger.warning("Rate limit exceeded for user %s", user_id)
            await message.answer("Слишком много запросов, попробуйте позже.")
            data["rate_limited"] = True
            return

        data["rate_limited"] = False


# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Register middlewares
dp.message.middleware(TraceparentMiddleware())
dp.message.middleware(WhitelistMiddleware())
dp.message.middleware(RateLimitMiddleware())

# Initialize orchestrator components
classifier = IntentClassifier()
synthesizer = Synthesizer()
source_orchestrator = SourceOrchestrator()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command."""
    await message.answer(
        "Привет! Я — налоговый ассистент. Спрашивайте о ставках, сроках, "
        "сальдо ЕНС или расчётах налогов.\n\n"
        "Примеры:\n"
        "• Какая ставка НДС?\n"
        "• Покажи мои документы за Q1\n"
        "• Почему у меня переплата по НДС?"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Handle /help command."""
    await message.answer(
        "Доступные команды:\n"
        "/start — Начать работу\n"
        "/help — Показать справку\n"
        "/details — Полный текст статьи\n\n"
        "Текстовые запросы:\n"
        "• Справка по закону (RAG)\n"
        "• Фактические данные (1С)\n"
        "• Комбинированные запросы"
    )


@dp.message()
async def handle_message(message: types.Message, data: Dict):
    """Handle text messages from users.

    Pipeline:
    1. Check whitelist (WhitelistMiddleware)
    2. Check rate limit (RateLimitMiddleware)
    3. Classify intent
    4. Fetch sources (RAG + 1C)
    5. Synthesize answer
    6. Send response
    """
    # Check if blocked by whitelist
    if data.get("blocked"):
        return

    # Check if rate limited
    if data.get("rate_limited"):
        return

    traceparent = data.get("traceparent", "")
    trace_id = data.get("trace_id", "")
    user_id = message.from_user.id

    logger.info(
        "Processing message from user %s (traceparent=%s): %s",
        user_id,
        traceparent[:20],
        message.text[:50],
    )

    # Step 1: Classify intent
    classification: ClassificationResult = classifier.classify(message.text)

    if classification.intent == Intent.UNKNOWN:
        # Clarifying question
        await message.answer(
            classification.clarifying_question or "Уточните, пожалуйста, ваш запрос."
        )
        return

    # Step 2: Fetch sources
    intent_str = classification.intent.value
    tax_type = classification.tax_type

    try:
        sources = source_orchestrator.fetch_sources(
            query=message.text,
            intent=intent_str,
            tax_type=tax_type,
        )
    except Exception as e:
        logger.error("Source fetch failed (trace_id=%s): %s", trace_id, e)
        await message.answer(
            "Произошла ошибка при обработке запроса. Попробуйте позже."
        )
        return

    # Step 3: Synthesize answer
    synthesis_request = SynthesisRequest(
        query=message.text,
        rag_results=sources.get("rag_results", []),
        one_c_data=sources.get("one_c_data"),
        traceparent=traceparent,
    )

    try:
        response = synthesizer.synthesize(synthesis_request)
        response = synthesizer.validate_and_reject(response)
    except Exception as e:
        logger.error("Synthesis failed (trace_id=%s): %s", trace_id, e)
        await message.answer(
            "Произошла ошибка при синтезе ответа. Попробуйте позже."
        )
        return

    if not response.citation_valid:
        await message.answer(
            "Не удалось подтвердить ответ источником. Пожалуйста, уточните запрос."
        )
        return

    # Step 4: Send response
    await message.answer(response.answer)
    logger.info(
        "Response sent to user %s (trace_id=%s, sources=%s)",
        user_id,
        trace_id,
        response.sources_used,
    )


async def on_startup(bot: Bot):
    """Bot startup handler."""
    logger.info("Tax Assistant bot starting up...")

    # Validate bot token
    try:
        check_token(BOT_TOKEN)
        logger.info("Bot token is valid")
    except TokenValidationError:
        logger.error("Invalid bot token. Set BOT_TOKEN environment variable.")
        sys.exit(1)

    # Check whitelist
    if WHITELIST_IDS:
        logger.info("Whitelist enabled: %d users", len(WHITELIST_IDS))
    else:
        logger.warning("Whitelist is empty — bot is open to all users!")

    # Check RAG corpus
    corpus_path = Path("rag/data/nk_rf.json")
    if corpus_path.exists():
        count = source_orchestrator.rag_source.preload(str(corpus_path))
        logger.info("RAG corpus preloaded: %d chunks", count)
    else:
        logger.warning("RAG corpus not found: %s", corpus_path)

    logger.info("Bot startup complete")


async def on_shutdown(bot: Bot):
    """Bot shutdown handler."""
    logger.info("Bot shutting down...")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Starting Tax Assistant bot...")
    dp.run_polling(bot)
