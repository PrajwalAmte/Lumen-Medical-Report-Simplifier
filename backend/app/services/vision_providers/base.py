"""Abstract base class for all vision providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from PIL import Image

from app.models.extraction import PageContent


class VisionProvider(ABC):

    @abstractmethod
    async def extract(
        self,
        img: Image.Image,
        section_types: List[str],
        page_num: int,
    ) -> PageContent:
        """
        Send the page image to the vision model and return a PageContent.

        section_types drives prompt selection.  An empty list → "general" prompt.
        Implementations must never raise — return a PageContent with empty lines
        on failure so the caller can fall back to a cheaper tier.
        """
        ...
