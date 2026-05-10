"""
Vision extraction orchestrator — the sync entry point for the OCR pipeline.

The OCR pipeline (ocr.py) is called from a ThreadPoolExecutor thread that
has no running event loop, so asyncio.run() is safe to use here.

Primary API:
    extract_page_content(img, page_num, section_types) -> PageContent
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from PIL import Image

from app.models.extraction import PageContent
from app.services.vision_providers import get_vision_provider

logger = logging.getLogger(__name__)


def extract_page_content(
    img: Image.Image,
    page_num: int,
    section_types: List[str],
) -> PageContent:
    """
    Run vision extraction synchronously.

    Delegates to the configured VisionProvider (OpenAI or local Ollama).
    Returns a PageContent with empty lines if the provider fails; the caller
    (ocr._vision_extract) treats empty lines as a signal to fall back to
    the Tesseract result.
    """
    provider = get_vision_provider()
    try:
        return asyncio.run(provider.extract(img, section_types, page_num))
    except Exception as exc:
        logger.warning("vision_extractor: unexpected error on page %d: %s", page_num, exc)
        return PageContent(page_num=page_num, lines=[], raw_text="")
