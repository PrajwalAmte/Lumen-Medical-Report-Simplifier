"""
Document classifier — heuristic routing for scanned page images.

Two public APIs:

    classify_page(img)          -> "paddle_table" | "tesseract"
        Image-level signal: detects ruling-line table structure.

    detect_sections(text)       -> list[str]
        Text-level signal: returns semantic section tags found in the text.
        Tags: "ecg", "echo", "radiology".  Empty list = generic lab report.

    needs_vision_tier(page)     -> bool
        Returns True when OCR output is too sparse to be useful and a
        vision LLM pass should be attempted.

All three are intentionally heuristic (no ML inference) so they are fast,
deterministic, and trivially testable.

Tuning constants are module-level so they can be overridden in tests without
patching internals.
"""

from __future__ import annotations

import re
from typing import List

import numpy as np
from PIL import Image

from app.models.extraction import PageContent

TABLE_LINE_FRACTION = 0.40
DARK_PIXEL_THRESHOLD = 80
MIN_QUALIFYING_ROWS = 3

VISION_MIN_LINES = 3
VISION_MIN_CHARS = 80

_ECG_PATTERN = re.compile(
    r"\b(ecg|ekg|electrocardiogram|st[- ]segment|qrs|qtc|qt[- ]interval"
    r"|pr[- ]interval|sinus[- ]rhythm|atrial[- ]fibrillation|bundle[- ]branch"
    r"|tachycardia|bradycardia|ischemi|infarction|lbbb|rbbb|avr|avl|avf"
    r"|lead[- ][iv]+)\b",
    re.IGNORECASE,
)

_ECHO_PATTERN = re.compile(
    r"\b(echocardiogram|2d[- ]echo|doppler|ejection[- ]fraction|lvef"
    r"|lvedd|lvesd|fractional[- ]shortening|diastolic[- ]function"
    r"|mitral[- ]valve|tricuspid[- ]valve|aortic[- ]valve|pericardial[- ]effusion"
    r"|wall[- ]motion|rwma|tapse|e/a[- ]ratio)\b",
    re.IGNORECASE,
)

_RADIOLOGY_PATTERN = re.compile(
    r"\b(x-?ray|radiograph|ct[- ]scan|mri|opacity|consolidation"
    r"|cardiomegaly|pleural[- ]effusion|pneumothorax|fracture|lesion"
    r"|calcification|chest[- ]pa|lateral[- ]view|impression:)\b",
    re.IGNORECASE,
)


def _max_run_per_row(dark_mask: np.ndarray) -> np.ndarray:
    """
    Return the longest contiguous True run for each row of a 2-D boolean array.

    Uses padded diff approach: O(H * W) but fully vectorised via numpy so fast
    even at 300 DPI (~2480 × 3508 for A4).

    Returns a 1-D int array of shape (H,).
    """
    H, W = dark_mask.shape
    padded = np.zeros((H, W + 2), dtype=np.int8)
    padded[:, 1 : W + 1] = dark_mask.astype(np.int8)
    diffs = np.diff(padded, axis=1)
    run_lengths = np.zeros(H, dtype=np.int32)
    for h in range(H):
        row = diffs[h]
        starts = np.where(row == 1)[0]
        ends = np.where(row == -1)[0]
        if starts.size:
            run_lengths[h] = int((ends - starts).max())
    return run_lengths


def classify_page(img: Image.Image) -> str:
    """
    Classify a rasterised page as "paddle_table" or "tesseract".

    A page is classified as a table if at least MIN_QUALIFYING_ROWS scanlines
    each contain a contiguous dark pixel run that spans TABLE_LINE_FRACTION or
    more of the image width.  This reliably detects printed ruling lines in
    formatted lab report tables without requiring computer vision libraries.
    """
    gray = np.array(img.convert("L"))
    width = gray.shape[1]
    min_run = int(width * TABLE_LINE_FRACTION)

    dark_mask = gray <= DARK_PIXEL_THRESHOLD
    run_lengths = _max_run_per_row(dark_mask)
    qualifying = int((run_lengths >= min_run).sum())

    return "paddle_table" if qualifying >= MIN_QUALIFYING_ROWS else "tesseract"


def detect_sections(text: str) -> List[str]:
    """
    Return the semantic section types present in a page of text.

    Uses compiled keyword regexes — fast enough to run on every page.
    The returned list determines which vision prompt template is used when
    the page is routed to the vision extraction tier.

    Returns an empty list for ordinary lab result pages.
    """
    sections: List[str] = []
    if _ECG_PATTERN.search(text):
        sections.append("ecg")
    if _ECHO_PATTERN.search(text):
        sections.append("echo")
    if _RADIOLOGY_PATTERN.search(text):
        sections.append("radiology")
    return sections


def needs_vision_tier(page: PageContent) -> bool:
    """
    Return True when the OCR output is too sparse to trust.

    A page qualifies if it has fewer than VISION_MIN_LINES non-empty lines
    OR its total character count is below VISION_MIN_CHARS.  These thresholds
    capture genuinely degraded scans where Tesseract produced garbage while
    leaving normal low-density pages (e.g. a single-value result page) as-is.
    """
    if len(page.lines) < VISION_MIN_LINES:
        return True
    return len(page.raw_text.replace(" ", "").replace("\n", "")) < VISION_MIN_CHARS
