"""
Tests for Phase 3 — Structural OCR tier.

Coverage:
    document_classifier.classify_page  — table vs. plain-text heuristic
    structural_ocr.extract_page_content — table cell extraction via mocked PPStructure
    ocr.extract_pages (integration)     — end-to-end routing to structural tier
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from app.models.extraction import PageContent


def _make_white_image(width: int = 400, height: int = 200) -> Image.Image:
    return Image.fromarray(np.full((height, width), 255, dtype=np.uint8), mode="L")


def _make_table_image(width: int = 400, height: int = 200, n_lines: int = 5) -> Image.Image:
    """Return a greyscale PIL Image with n_lines horizontal black ruling lines."""
    arr = np.full((height, width), 255, dtype=np.uint8)
    step = height // (n_lines + 1)
    for k in range(1, n_lines + 1):
        y = k * step
        arr[y, :] = 0
    return Image.fromarray(arr, mode="L")


TABLE_HTML = (
    "<table>"
    "<tr><td>Haemoglobin</td><td>13.5</td><td>g/dL</td><td>13.0-17.0</td></tr>"
    "<tr><td>RBC Count</td><td>4.5</td><td>million/μL</td><td>4.5-5.5</td></tr>"
    "<tr><td>Platelet Count</td><td>220</td><td>×10³/μL</td><td>150-400</td></tr>"
    "</table>"
)

EXPECTED_LINES = [
    "Haemoglobin  13.5  g/dL  13.0-17.0",
    "RBC Count  4.5  million/μL  4.5-5.5",
    "Platelet Count  220  ×10³/μL  150-400",
]


class TestClassifyPage:
    def test_table_image_classified_as_paddle_table(self):
        """Image with 5 full-width ruling lines must be routed to structural OCR."""
        from app.services.document_classifier import classify_page

        img = _make_table_image(width=800, height=400, n_lines=5)
        assert classify_page(img) == "paddle_table"

    def test_plain_white_image_classified_as_tesseract(self):
        """All-white image has no ruling lines — must fall back to Tesseract."""
        from app.services.document_classifier import classify_page

        img = _make_white_image(width=800, height=400)
        assert classify_page(img) == "tesseract"

    def test_short_horizontal_strokes_do_not_qualify(self):
        """Short dark segments (<40% width) must not trigger paddle_table."""
        from app.services.document_classifier import classify_page

        arr = np.full((200, 400), 255, dtype=np.uint8)
        for y in [50, 100, 150]:
            arr[y, :80] = 0
        img = Image.fromarray(arr, mode="L")
        assert classify_page(img) == "tesseract"

    def test_fewer_than_min_lines_does_not_qualify(self):
        """Only 2 qualifying rows (< MIN_QUALIFYING_ROWS=3) → tesseract."""
        from app.services.document_classifier import classify_page

        img = _make_table_image(width=400, height=200, n_lines=2)
        assert classify_page(img) == "tesseract"


class TestHtmlTableToLines:
    def test_table_html_produces_correct_lines(self):
        from app.services.structural_ocr import _html_table_to_lines

        lines = _html_table_to_lines(TABLE_HTML)
        assert lines == EXPECTED_LINES

    def test_header_cells_included(self):
        from app.services.structural_ocr import _html_table_to_lines

        html = "<table><tr><th>Test</th><th>Value</th></tr><tr><td>Na</td><td>140</td></tr></table>"
        lines = _html_table_to_lines(html)
        assert lines == ["Test  Value", "Na  140"]

    def test_empty_cells_are_skipped(self):
        from app.services.structural_ocr import _html_table_to_lines

        html = "<table><tr><td>Glucose</td><td></td><td>5.4</td></tr></table>"
        lines = _html_table_to_lines(html)
        assert lines == ["Glucose  5.4"]

    def test_empty_html_returns_empty_list(self):
        from app.services.structural_ocr import _html_table_to_lines

        assert _html_table_to_lines("") == []


class TestRegionsToLines:
    def test_table_region_extracted(self):
        from app.services.structural_ocr import _regions_to_lines

        regions = [{"type": "table", "res": {"html": TABLE_HTML}}]
        lines = _regions_to_lines(regions)
        assert lines == EXPECTED_LINES

    def test_text_region_extracted(self):
        from app.services.structural_ocr import _regions_to_lines

        regions = [
            {
                "type": "text",
                "res": [
                    ([[0, 0], [100, 20]], ("Patient: John Doe", 0.98)),
                ],
            }
        ]
        lines = _regions_to_lines(regions)
        assert lines == ["Patient: John Doe"]

    def test_mixed_regions_ordered_correctly(self):
        from app.services.structural_ocr import _regions_to_lines

        regions = [
            {"type": "title", "res": [([[0, 0], [200, 20]], ("Lab Report", 0.99))]},
            {"type": "table", "res": {"html": "<table><tr><td>Hb</td><td>13.5</td></tr></table>"}},
        ]
        lines = _regions_to_lines(regions)
        assert lines[0] == "Lab Report"
        assert lines[1] == "Hb  13.5"

    def test_empty_region_list_returns_empty(self):
        from app.services.structural_ocr import _regions_to_lines

        assert _regions_to_lines([]) == []


class TestExtractPageContent:
    def _fake_engine(self, regions: list):
        engine = MagicMock()
        engine.return_value = regions
        return engine

    def test_table_cells_resolved_from_scanned_report(self):
        """
        Feed a scanned lab report image through extract_page_content with a
        mocked PPStructure engine and assert that each table row is a line.
        """
        from app.services import structural_ocr

        fake_regions = [{"type": "table", "res": {"html": TABLE_HTML}}]
        with patch.object(structural_ocr, "_get_engine", return_value=self._fake_engine(fake_regions)):
            img = _make_white_image()
            page = structural_ocr.extract_page_content(img, page_num=1)

        assert page.page_num == 1
        assert page.lines == EXPECTED_LINES
        assert "Haemoglobin" in page.raw_text
        assert "RBC Count" in page.raw_text

    def test_mixed_page_text_and_table(self):
        """Header text followed by table rows should produce ordered lines."""
        from app.services import structural_ocr

        fake_regions = [
            {"type": "title", "res": [([[0, 0], [200, 20]], ("Complete Blood Count", 0.99))]},
            {"type": "table", "res": {"html": "<table><tr><td>WBC</td><td>6.5</td><td>×10³/μL</td></tr></table>"}},
        ]
        with patch.object(structural_ocr, "_get_engine", return_value=self._fake_engine(fake_regions)):
            img = _make_white_image()
            page = structural_ocr.extract_page_content(img, page_num=2)

        assert page.lines[0] == "Complete Blood Count"
        assert page.lines[1] == "WBC  6.5  ×10³/μL"

    def test_paddle_ocr_failure_returns_empty_page_content(self):
        """If PPStructure raises, extract_page_content must return empty PageContent."""
        from app.services import structural_ocr

        engine = MagicMock(side_effect=RuntimeError("CUDA out of memory"))
        with patch.object(structural_ocr, "_get_engine", return_value=engine):
            img = _make_white_image()
            page = structural_ocr.extract_page_content(img, page_num=1)

        assert page.page_num == 1
        assert page.lines == []
        assert page.raw_text == ""

    def test_empty_regions_returns_empty_page_content(self):
        from app.services import structural_ocr

        with patch.object(structural_ocr, "_get_engine", return_value=self._fake_engine([])):
            img = _make_white_image()
            page = structural_ocr.extract_page_content(img, page_num=3)

        assert page.lines == []


class TestOcrRoutingIntegration:
    """Integration tests: extract_pages routes scanned pages through the correct tier."""

    def _make_fake_pdf_page(self, text: str = ""):
        page = MagicMock()
        page.extract_text.return_value = text
        return page

    def test_scanned_table_page_routed_to_structural_ocr(self):
        """
        When pdfplumber returns no native text and classify_page returns
        'paddle_table', extract_pages must use structural_ocr and return
        the cell-level lines.
        """
        from app.services import ocr

        fake_page_content = PageContent(
            page_num=1,
            lines=EXPECTED_LINES,
            raw_text="\n".join(EXPECTED_LINES),
        )
        fake_img = _make_white_image()
        fake_pdf = MagicMock()
        fake_pdf.pages = [self._make_fake_pdf_page(text="")]
        fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
        fake_pdf.__exit__ = MagicMock(return_value=False)

        with patch("app.services.ocr.pdfplumber.open", return_value=fake_pdf), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="paddle_table"), \
             patch("app.services.ocr._structural_extract", return_value=fake_page_content):

            pages = ocr.extract_pages("scanned_report.pdf")

        assert len(pages) == 1
        assert pages[0].lines == EXPECTED_LINES

    def test_scanned_non_table_page_routed_to_tesseract(self):
        """classify_page returning 'tesseract' must bypass structural OCR."""
        from app.services import ocr

        fake_img = _make_white_image()
        fake_pdf = MagicMock()
        fake_pdf.pages = [self._make_fake_pdf_page(text="")]
        fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
        fake_pdf.__exit__ = MagicMock(return_value=False)

        with patch("app.services.ocr.pdfplumber.open", return_value=fake_pdf), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="tesseract"), \
             patch("app.services.ocr._image_to_page_content") as mock_tesseract:

            mock_tesseract.return_value = PageContent(page_num=1, lines=["Plain text"], raw_text="Plain text")
            pages = ocr.extract_pages("scanned_report.pdf")

        mock_tesseract.assert_called_once_with(fake_img, page_num=1)
        assert pages[0].lines == ["Plain text"]

    def test_digital_pdf_page_skips_classifier(self):
        """Pages with native text must never call classify_page."""
        from app.services import ocr

        fake_pdf = MagicMock()
        fake_pdf.pages = [self._make_fake_pdf_page(text="Glucose  5.4  mmol/L  3.9-6.1")]
        fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
        fake_pdf.__exit__ = MagicMock(return_value=False)

        with patch("app.services.ocr.pdfplumber.open", return_value=fake_pdf), \
             patch("app.services.ocr.classify_page") as mock_classifier:

            pages = ocr.extract_pages("digital_report.pdf")

        mock_classifier.assert_not_called()
        assert "Glucose" in pages[0].raw_text

    def test_structural_ocr_fallback_to_tesseract_on_empty_result(self):
        """
        If structural OCR returns an empty PageContent (PaddleOCR failed),
        _structural_extract must fall back to Tesseract.
        """
        from app.services import structural_ocr as struct_mod
        from app.services import ocr

        fake_img = _make_white_image()
        fake_pdf = MagicMock()
        fake_pdf.pages = [self._make_fake_pdf_page(text="")]
        fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
        fake_pdf.__exit__ = MagicMock(return_value=False)

        tesseract_result = PageContent(page_num=1, lines=["Hb   13.5  g/dL"], raw_text="Hb   13.5  g/dL")

        with patch("app.services.ocr.pdfplumber.open", return_value=fake_pdf), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="paddle_table"), \
             patch.object(struct_mod, "_get_engine", return_value=MagicMock(return_value=[])), \
             patch("app.services.ocr._image_to_page_content", return_value=tesseract_result):

            pages = ocr.extract_pages("hybrid_report.pdf")

        assert pages[0].lines == ["Hb   13.5  g/dL"]
