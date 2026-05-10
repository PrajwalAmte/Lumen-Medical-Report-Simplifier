"""
Vision provider abstraction — swap backends without touching extraction logic.

Factory usage:
    from app.services.vision_providers import get_vision_provider
    provider = get_vision_provider()
    page = await provider.extract(img, section_types, page_num)

PHI mode:
    Set VISION_PROVIDER=local in the environment.  The local provider routes
    to an on-premise Ollama instance so no image data leaves the server.
"""

from app.services.vision_providers.base import VisionProvider
from app.services.vision_providers.factory import get_vision_provider

__all__ = ["VisionProvider", "get_vision_provider"]
