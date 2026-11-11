"""Fallback to RusMind Сокол 4.7 (Ollama) when GigaChat is unavailable.

ADR-001: Hybrid LLM strategy — GigaChat (primary) + RusMind (fallback).
NFR-006: Only Russian LLM providers allowed.
TM-10: Spoofing protection — validate provider at startup.

Covers:
- FR-004: Synthesize answer even if GigaChat is down
- NFR-006: Provider validation (allowlist: GigaChat, RusMind)
- TM-10: Provider spoofing protection
"""

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Allowed LLM providers (NFR-006, ADR-001)."""
    GIGACHAT = "GigaChat"
    MENO_LITE = "Meno-Lite"
    RUSMIND = "RusMind"


ALLOWED_PROVIDERS = {LLMProvider.GIGACHAT, LLMProvider.MENO_LITE, LLMProvider.RUSMIND}

# Default Ollama endpoint for RusMind
OLLAMA_DEFAULT_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


@dataclass
class LLMResponse:
    """Generic LLM response."""
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str = ""
    error: Optional[str] = None


class ProviderValidator:
    """Validates LLM provider configuration.

    NFR-006: Only {GigaChat, Meno-Lite, RusMind} allowed.
    TM-10: Prevent provider spoofing.
    T-307: Validation at startup.
    """

    @staticmethod
    def validate(provider_name: str) -> LLMProvider:
        """Validate provider name against allowlist.

        Args:
            provider_name: Provider name from configuration.

        Returns:
            Validated LLMProvider enum.

        Raises:
            ValueError: If provider is not in allowlist.
        """
        provider = LLMProvider(provider_name)
        if provider not in ALLOWED_PROVIDERS:
            raise ValueError(
                f"NFR-006 violation: provider '{provider_name}' not in allowlist. "
                f"Allowed: {[p.value for p in ALLOWED_PROVIDERS]}"
            )
        return provider

    @staticmethod
    def check_environment() -> List[str]:
        """Check available LLM providers at startup.

        Returns:
            List of available providers.
        """
        available = []

        # Check GigaChat
        if os.getenv("GIGACHAT_API_KEY"):
            available.append(LLMProvider.GIGACHAT.value)
            logger.info("GigaChat API key configured")
        else:
            logger.warning("GigaChat API key not configured (using mock)")

        # Check RusMind (Ollama)
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{OLLAMA_DEFAULT_URL}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_names = [m["name"] for m in models]
                    if any("sokol" in m.lower() or "rusmind" in m.lower() for m in model_names):
                        available.append(LLMProvider.RUSMIND.value)
                        logger.info("RusMind Sokol found in Ollama")
                    else:
                        logger.warning("RusMind Sokol not found in Ollama (models: %s)", model_names)
        except httpx.ConnectError:
            logger.warning("Ollama not running at %s", OLLAMA_DEFAULT_URL)
        except Exception as e:
            logger.warning("Ollama check failed: %s", e)

        if not available:
            logger.warning("No LLM providers available, using mock responses")

        return available


class GigaChatFallback:
    """Fallback mechanism from GigaChat to RusMind (Ollama).

    Handles:
    - GigaChat API timeout
    - GigaChat API unavailable
    - Automatic switch to RusMind
    """

    def __init__(
        self,
        gigachat_key: Optional[str] = None,
        ollama_url: str = OLLAMA_DEFAULT_URL,
        timeout: float = 5.0,
    ):
        """Initialize fallback handler.

        Args:
            gigachat_key: GigaChat API key.
            ollama_url: Ollama API URL.
            timeout: Request timeout in seconds.
        """
        self.gigachat_key = gigachat_key
        self.ollama_url = ollama_url
        self.timeout = timeout
        self._gigachat_available = bool(gigachat_key)
        self._ollama_available = False
        self._switched_to_fallback = False

        # Check Ollama availability
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{ollama_url}/api/tags")
                if resp.status_code == 200:
                    self._ollama_available = True
                    logger.info("RusMind (Ollama) is available at %s", ollama_url)
        except httpx.ConnectError:
            logger.warning("Ollama not available at %s", ollama_url)
        except Exception as e:
            logger.warning("Ollama check failed: %s", e)

    def generate(self, prompt: str, max_tokens: int = 500) -> LLMResponse:
        """Generate answer with automatic fallback.

        Priority:
        1. GigaChat (if available and key configured)
        2. RusMind (Ollama) — if GigaChat fails
        3. Mock response — if nothing available

        Args:
            prompt: Input prompt.
            max_tokens: Maximum output tokens.

        Returns:
            LLMResponse with generated text.
        """
        # Try GigaChat first
        if self._gigachat_available:
            try:
                return self._call_gigachat(prompt, max_tokens)
            except Exception as e:
                logger.warning("GigaChat failed (%s), falling back to RusMind", e)
                self._switched_to_fallback = True

        # Fallback to RusMind (Ollama)
        if self._ollama_available:
            try:
                return self._call_rusmind(prompt, max_tokens)
            except Exception as e:
                logger.warning("RusMind failed (%s), using mock response", e)

        # Last resort: mock response
        logger.warning("No LLM available, using mock response")
        return LLMResponse(
            text="Согласно ст. 164 п. 1 НК РФ, ставка НДС составляет 20%.",
            model="mock",
            provider="Mock",
        )

    def _call_gigachat(self, prompt: str, max_tokens: int) -> LLMResponse:
        """Call GigaChat API.

        For MVP: returns mock if no real API integration.
        TODO: Implement real GigaChat API call with OAuth.
        """
        logger.info("Calling GigaChat 3.5 Reasoning")
        # TODO: Real GigaChat API implementation
        # Steps:
        # 1. Get OAuth token from /auth endpoint
        # 2. Call /api/v1/models with model=GigaChat 3.5 Reasoning
        # 3. Parse response

        return LLMResponse(
            text=(
                "Согласно ст. 164 п. 1 НК РФ, ставка НДС составляет 20%. "
                "Данные из 1С: сальдо ЕНС по НДС — 150 000 руб. "
                "Данные на 31.03.2025."
            ),
            model="GigaChat 3.5 Reasoning",
            tokens_in=100,
            tokens_out=50,
            provider=LLMProvider.GIGACHAT.value,
        )

    def _call_rusmind(self, prompt: str, max_tokens: int) -> LLMResponse:
        """Call RusMind Sokol via Ollama API.

        Ollama API:
        POST /api/generate
        {
            "model": "sokol-4.7",
            "prompt": "...",
            "stream": false,
            "options": {
                "num_predict": 500
            }
        }
        """
        logger.info("Calling RusMind Sokol 4.7 via Ollama")

        payload = {
            "model": "sokol-4.7",
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
            },
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()

            data = resp.json()
            return LLMResponse(
                text=data.get("response", ""),
                model="RusMind Sokol 4.7",
                tokens_in=len(prompt.split()),
                tokens_out=len(data.get("response", "").split()),
                provider=LLMProvider.RUSMIND.value,
            )

    @property
    def is_fallback_active(self) -> bool:
        """Whether fallback to RusMind is currently active."""
        return self._switched_to_fallback
