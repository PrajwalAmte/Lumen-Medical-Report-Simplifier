"""Vision provider factory."""

from __future__ import annotations

from app.core.config import settings
from app.services.vision_providers.base import VisionProvider

_instance: VisionProvider | None = None


def get_vision_provider() -> VisionProvider:
    """Return the configured vision provider singleton."""
    global _instance
    if _instance is None:
        _instance = _build()
    return _instance


def _build() -> VisionProvider:
    provider = settings.VISION_PROVIDER.lower()
    if provider == "local":
        from app.services.vision_providers.local_vision import LocalVisionProvider
        return LocalVisionProvider()
    from app.services.vision_providers.openai_vision import OpenAIVisionProvider
    return OpenAIVisionProvider()
