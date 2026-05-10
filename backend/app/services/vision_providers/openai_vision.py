"""
OpenAI vision provider — GPT-4o image understanding.

Routes complex/degraded/multi-modal pages through GPT-4o's vision API.
The image is resized to fit within VISION_MAX_SIDE_PX on the long side
before encoding to keep token costs predictable.

Config:
    VISION_MODEL          (default: gpt-4o)
    OPENAI_API_KEY
    VISION_MAX_SIDE_PX    (default: 1024)
    VISION_TIMEOUT_SEC    (default: 60)

SECURITY: Images are sent to OpenAI's API.  For PHI-sensitive deployments,
set VISION_PROVIDER=local to keep data on-premise.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import List, Optional

from openai import AsyncOpenAI
from PIL import Image

from app.core.config import settings
from app.models.extraction import PageContent
from app.services.vision_providers.base import VisionProvider
from app.services.vision_providers.prompts import pick_prompt

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set; cannot use OpenAI vision provider")
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _resize_image(img: Image.Image, max_side: int) -> Image.Image:
    """Resize so the longer dimension is at most max_side, maintaining aspect ratio."""
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    scale = max_side / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _encode_image(img: Image.Image) -> str:
    """Return a base64-encoded PNG string suitable for an OpenAI data URI."""
    img = _resize_image(img.convert("RGB"), settings.VISION_MAX_SIDE_PX)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _response_to_lines(text: str) -> List[str]:
    """Split model output into non-empty lines."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


class OpenAIVisionProvider(VisionProvider):
    """Vision extraction via OpenAI GPT-4o."""

    async def extract(
        self,
        img: Image.Image,
        section_types: List[str],
        page_num: int,
    ) -> PageContent:
        try:
            system_prompt, user_prompt = pick_prompt(section_types)
            b64 = _encode_image(img)
            client = _get_client()

            response = await client.chat.completions.create(
                model=settings.VISION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
                max_tokens=2048,
                temperature=0.0,
                timeout=settings.VISION_TIMEOUT_SEC,
            )

            output = (response.choices[0].message.content or "").strip()
            usage = getattr(response, "usage", None)
            if usage:
                logger.info(
                    "OpenAI vision — page=%d model=%s prompt_tokens=%d completion_tokens=%d",
                    page_num,
                    settings.VISION_MODEL,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                )

            lines = _response_to_lines(output)
            return PageContent(page_num=page_num, lines=lines, raw_text="\n".join(lines))

        except Exception as exc:
            logger.warning("OpenAI vision failed for page %d: %s", page_num, exc)
            return PageContent(page_num=page_num, lines=[], raw_text="")
