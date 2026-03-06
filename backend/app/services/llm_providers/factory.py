"""
Provider factory — returns the correct LLMProvider singleton.
LLM_PROVIDER options: groq | openai | llama | ollama
"""

from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_providers.base import LLMProvider

logger = get_logger("llm.factory")

_provider: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """Return a lazily-initialised provider singleton."""
    global _provider
    if _provider is not None:
        return _provider

    name = settings.LLM_PROVIDER.lower().strip()
    logger.info(f"Initialising LLM provider: {name}")

    if name == "groq":
        from app.services.llm_providers.groq_provider import GroqProvider
        _provider = GroqProvider()

    elif name == "openai":
        from app.services.llm_providers.openai_provider import OpenAIProvider
        _provider = OpenAIProvider()

    elif name in ("llama", "ollama"):
        from app.services.llm_providers.llama_provider import LlamaProvider
        _provider = LlamaProvider()

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER={name!r}. "
            f"Supported: groq, openai, llama, ollama"
        )

    return _provider


def reset_provider():
    """Reset the singleton (useful in tests)."""
    global _provider
    _provider = None
