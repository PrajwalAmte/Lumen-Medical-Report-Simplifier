"""
Local vision provider — Ollama-hosted multimodal model (PHI-compliant).

All image data stays on-premise.  Default model: llava:13b.
Uses Ollama's native /api/chat endpoint; no data is sent to external APIs.

Config:
    LOCAL_VISION_ENDPOINT    (default: http://localhost:11434)
    LOCAL_VISION_MODEL       (default: llava:13b)
    VISION_MAX_SIDE_PX       (default: 1024)
    VISION_TIMEOUT_SEC       (default: 60)

PHI compliance note: verify your Ollama instance has no external telemetry
and runs within your network perimeter before processing patient images.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import List

import httpx
from PIL import Image

from app.core.config import settings
from app.models.extraction import PageContent
from app.services.vision_providers.base import VisionProvider
from app.services.vision_providers.prompts import pick_prompt

logger = logging.getLogger(__name__)


def _resize_image(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    scale = max_side / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _encode_image(img: Image.Image) -> str:
    img = _resize_image(img.convert("RGB"), settings.VISION_MAX_SIDE_PX)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _response_to_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


class LocalVisionProvider(VisionProvider):
    """Vision extraction via a locally-hosted Ollama vision model."""

    async def extract(
        self,
        img: Image.Image,
        section_types: List[str],
        page_num: int,
    ) -> PageContent:
        try:
            system_prompt, user_prompt = pick_prompt(section_types)
            b64 = _encode_image(img)
            endpoint = settings.LOCAL_VISION_ENDPOINT.rstrip("/")
            model = settings.LOCAL_VISION_MODEL

            # Ollama /api/chat accepts images as a list of base64 strings
            # alongside the text content of the message.
            payload = {
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt,
                        "images": [b64],
                    },
                ],
            }

            async with httpx.AsyncClient(timeout=settings.VISION_TIMEOUT_SEC) as client:
                resp = await client.post(f"{endpoint}/api/chat", json=payload)
                resp.raise_for_status()

            data = resp.json()
            output = data.get("message", {}).get("content", "").strip()

            logger.info(
                "Local vision — page=%d model=%s chars=%d",
                page_num,
                model,
                len(output),
            )

            lines = _response_to_lines(output)
            return PageContent(page_num=page_num, lines=lines, raw_text="\n".join(lines))

        except Exception as exc:
            logger.warning("Local vision failed for page %d: %s", page_num, exc)
            return PageContent(page_num=page_num, lines=[], raw_text="")
