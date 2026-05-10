"""
OCR service — extracts text from PDFs and images.

Primary API:
  extract_pages(file_path) -> List[PageContent]   — per-page structured output
  extract_text(file_path)  -> str                 — backward-compatible flat string

Per-page output preserves line structure so the parser can distinguish
result rows, range rows, formula rows, and section headers.  The flat
extract_text() wrapper joins all pages with double newlines for callers
that have not yet migrated to the new pipeline.

OCR strategy:
  1. pdfplumber native text extraction (digital PDFs, fastest, most accurate).
  2. If native extraction yields nothing, the page image is classified:
       a. document_classifier.classify_page detects ruling-line table structure.
       b. "paddle_table" pages go to structural_ocr.extract_page_content
          (PaddleOCR PPStructure — table-aware, cell-level extraction).
       c. "tesseract" pages go to the existing Tesseract path.
  3. After any scanned extraction, detect_sections checks the resulting text
     for special section types (ECG, echo, radiology).  If specialised sections
     are found, or the page output is too sparse (needs_vision_tier), the page
     is promoted to the Vision LLM tier (GPT-4o / Ollama LLaVA).
     Tesseract parameters:
       - DPI 300  (vs. 200) — captures small fonts and fine table lines
       - PSM 3    (auto-segment) — handles mixed single/multi-column layouts
       - Binary threshold 160  — optimised for scanned laser-printed reports
"""

from __future__ import annotations

import os
from typing import List

import logging

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance, ImageFilter

from app.models.extraction import PageContent
from app.services.document_classifier import classify_page, detect_sections, needs_vision_tier

logger = logging.getLogger(__name__)



def _preprocess_image(img: Image.Image) -> Image.Image:
    """Greyscale → denoise → contrast boost → binarise for Tesseract."""
    img = img.convert("L")
    img = img.filter(ImageFilter.MedianFilter())
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2)
    # Threshold raised to 160 (from 140) — reduces salt-and-pepper noise from
    # scanned lab reports while keeping faint print legible.
    img = img.point(lambda x: 0 if x < 160 else 255, "1")
    return img



def _ocr_image(img: Image.Image) -> str:
    """
    Run Tesseract on a preprocessed page image.

    PSM 3 (fully automatic page segmentation) is used instead of PSM 6
    (uniform block) because Indian lab reports often mix a single-column
    patient-info block with a multi-column CBC or lipid table.  PSM 3 lets
    Tesseract choose the best layout model per region.
    """
    img = _preprocess_image(img)
    return pytesseract.image_to_string(img, config="--psm 3 --dpi 300")



def _image_to_page_content(img: Image.Image, page_num: int) -> PageContent:
    raw_text = _ocr_image(img).strip()
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    return PageContent(page_num=page_num, lines=lines, raw_text=raw_text)


def _native_text_to_page_content(text: str, page_num: int) -> PageContent:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return PageContent(page_num=page_num, lines=lines, raw_text=text.strip())


def _structural_extract(img: Image.Image, page_num: int) -> PageContent:
    """
    Attempt PaddleOCR table extraction; fall back to Tesseract if it fails
    or returns no lines.  Local import keeps the top-level module load fast
    and avoids circular imports.
    """
    try:
        from app.services.structural_ocr import extract_page_content
        page = extract_page_content(img, page_num)
        if page.lines:
            return page
        logger.warning("Structural OCR returned no lines for page %d, falling back to Tesseract", page_num)
    except Exception as exc:
        logger.warning("Structural OCR failed for page %d (%s), falling back to Tesseract", page_num, exc)
    return _image_to_page_content(img, page_num)


def _vision_extract(
    img: Image.Image,
    page_num: int,
    section_types: list,
    fallback: PageContent,
) -> PageContent:
    """
    Attempt vision LLM extraction; return fallback PageContent if disabled or failed.

    section_types is passed to the vision provider to select the correct prompt.
    fallback is the Tesseract/Paddle result — preserved when vision returns nothing.
    """
    from app.core.config import settings
    if not settings.VISION_ENABLED:
        return fallback
    try:
        from app.services.vision_extractor import extract_page_content as vision_extract
        page = vision_extract(img, page_num, section_types)
        if page.lines:
            page.detected_sections = fallback.detected_sections
            return page
        logger.warning("Vision OCR returned no lines for page %d, keeping OCR result", page_num)
    except Exception as exc:
        logger.warning("Vision OCR failed for page %d (%s), keeping OCR result", page_num, exc)
    return fallback



def extract_pages(file_path: str) -> List[PageContent]:
    """
    Extract text from a PDF or image file, preserving per-page line structure.

    For PDFs:
      - pdfplumber native extraction is tried first (fast, exact).
      - Pages with no native text fall back to Tesseract OCR individually
        (handles hybrid PDFs where some pages are scanned and some are digital).

    For images: a single PageContent (page_num=1) is returned.

    Returns an empty list only if the file is unreadable.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".pdf":
        img = Image.open(file_path)
        page = _image_to_page_content(img, page_num=1)
        sections = detect_sections(page.raw_text)
        page.detected_sections = sections
        vision_triggers = {"ecg", "echo", "radiology"}
        if vision_triggers.intersection(sections) or needs_vision_tier(page):
            page = _vision_extract(img, page_num=1, section_types=sections or ["general"], fallback=page)
        return [page]

    pages: List[PageContent] = []
    with pdfplumber.open(file_path) as pdf:
        for i, pdf_page in enumerate(pdf.pages, start=1):
            native = pdf_page.extract_text() or ""
            if native.strip():
                pages.append(_native_text_to_page_content(native, page_num=i))
            else:
                # Scanned page — rasterise, classify, then route to the
                # appropriate OCR tier (structural PaddleOCR or Tesseract).
                images = convert_from_path(
                    file_path,
                    dpi=300,
                    first_page=i,
                    last_page=i,
                )
                if images:
                    img = images[0]
                    tier = classify_page(img)
                    if tier == "paddle_table":
                        page = _structural_extract(img, page_num=i)
                    else:
                        page = _image_to_page_content(img, page_num=i)

                    sections = detect_sections(page.raw_text)
                    page.detected_sections = sections
                    vision_triggers = {"ecg", "echo", "radiology"}
                    if vision_triggers.intersection(sections) or needs_vision_tier(page):
                        page = _vision_extract(
                            img,
                            page_num=i,
                            section_types=sections or ["general"],
                            fallback=page,
                        )
                    pages.append(page)

    return pages


def extract_text(file_path: str) -> str:
    """
    Backward-compatible flat string extraction.

    Joins all pages with double newlines.  New code should use extract_pages()
    to benefit from per-line classification and candidate scoring.
    """
    pages = extract_pages(file_path)
    return "\n\n".join(p.raw_text for p in pages).strip()



def _extract_from_image(file_path: str) -> str:
    img = Image.open(file_path)
    return _image_to_page_content(img, page_num=1).raw_text


def _extract_from_pdf(file_path: str) -> str:
    pages = extract_pages(file_path)
    return "\n\n".join(p.raw_text for p in pages).strip()

