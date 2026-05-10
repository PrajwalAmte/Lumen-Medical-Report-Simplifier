"""
Structural OCR tier — PaddleOCR table extraction for scanned lab reports.

Uses PPStructure (layout analysis + table recognition) when the document
classifier routes a page here.  Table cells are extracted in reading order
and joined into lines that the downstream parser can classify as result rows,
range rows, or headers.

The engine is initialised lazily on first call so the import cost is not
paid unless a page actually reaches this tier.

Primary API:
    extract_page_content(img, page_num) -> PageContent
"""

from __future__ import annotations

import logging
from html.parser import HTMLParser
from typing import List, Optional

import numpy as np
from PIL import Image

from app.models.extraction import PageContent

logger = logging.getLogger(__name__)

_engine: Optional[object] = None


def _get_engine():
    global _engine
    if _engine is None:
        from paddleocr import PPStructure
        _engine = PPStructure(table=True, ocr=True, show_log=False, lang="en")
    return _engine


class _RowCollector(HTMLParser):
    """Collect table rows from PPStructure's HTML output as lists of cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._current_row: List[str] = []
        self._in_cell = False
        self._buf = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False
            cell_text = self._buf.strip()
            if cell_text:
                self._current_row.append(cell_text)
            self._buf = ""
        elif tag == "tr" and self._current_row:
            self.rows.append(self._current_row)
            self._current_row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf += data


def _html_table_to_lines(html: str) -> List[str]:
    """Collapse each HTML table row into a two-space-separated text line."""
    collector = _RowCollector()
    collector.feed(html)
    return ["  ".join(row) for row in collector.rows if row]


def _regions_to_lines(regions: list) -> List[str]:
    """
    Convert a PPStructure region list into ordered text lines.

    PPStructure returns regions sorted top-to-bottom by bbox.  Table regions
    emit one line per row; text and title regions emit one line per OCR block.
    Non-table OCR results come as lists of (bbox, (text, confidence)) tuples.
    """
    lines: List[str] = []
    for region in regions:
        rtype = region.get("type", "")
        res = region.get("res", {})

        if rtype == "table":
            html = res.get("html", "") if isinstance(res, dict) else ""
            if html:
                lines.extend(_html_table_to_lines(html))
        else:
            if isinstance(res, list):
                for item in res:
                    if not (isinstance(item, (list, tuple)) and len(item) == 2):
                        continue
                    _bbox, txt_conf = item
                    if isinstance(txt_conf, (list, tuple)) and txt_conf:
                        text = txt_conf[0]
                    elif isinstance(txt_conf, str):
                        text = txt_conf
                    else:
                        continue
                    if isinstance(text, str) and text.strip():
                        lines.append(text.strip())

    return lines


def extract_page_content(img: Image.Image, page_num: int) -> PageContent:
    """
    Run PPStructure on a rasterised page image and return a PageContent.

    Returns a PageContent with empty lines if PPStructure fails; the caller
    (ocr.py) treats an empty result as a signal to fall back to Tesseract.

    img must be a PIL Image (any mode); it is converted to RGB internally
    because PPStructure expects a three-channel array.
    """
    try:
        img_array = np.array(img.convert("RGB"))
        regions = _get_engine()(img_array)
        lines = _regions_to_lines(regions)
        raw_text = "\n".join(lines)
        return PageContent(page_num=page_num, lines=lines, raw_text=raw_text)
    except Exception as exc:
        logger.warning("PPStructure failed on page %d: %s", page_num, exc)
        return PageContent(page_num=page_num, lines=[], raw_text="")
