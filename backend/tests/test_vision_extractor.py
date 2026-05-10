"""
Tests for Phase 4 — Vision Extraction Tier.

Coverage:
    document_classifier.detect_sections   — keyword-based section tagging
    document_classifier.needs_vision_tier — sparsity signal
    vision_providers.prompts.pick_prompt  — prompt selection per section
    vision_providers.openai_vision        — OpenAI provider with mocked client
    vision_providers.local_vision         — local Ollama provider with mocked httpx
    vision_extractor.extract_page_content — sync orchestrator
    ocr.extract_pages (integration)       — end-to-end vision routing
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from app.models.extraction import PageContent


def _white_img(w: int = 200, h: int = 200) -> Image.Image:
    return Image.fromarray(np.full((h, w), 255, dtype=np.uint8), mode="L")


ECG_TEXT = (
    "ECG Report\n"
    "Heart Rate  72  bpm\n"
    "PR Interval  160  ms\n"
    "QRS Duration  90  ms\n"
    "QTc  420  ms\n"
    "Sinus rhythm, normal ECG"
)

ECHO_TEXT = (
    "2D Echocardiogram\n"
    "EF  55  %\n"
    "LVEDD  48  mm\n"
    "Mitral Valve  Normal\n"
    "Diastolic Function  Grade I"
)

RADIOLOGY_TEXT = (
    "Chest X-Ray PA View\n"
    "Findings: No active consolidation.\n"
    "No pleural effusion.\n"
    "Impression: Normal chest radiograph"
)

LAB_TEXT = (
    "Haemoglobin  13.5  g/dL  13.0-17.0\n"
    "RBC  4.5  million/uL  4.5-5.5\n"
    "WBC  6500  /uL  4000-11000\n"
    "Platelet Count  220  thousand/uL  150-400"
)


class TestDetectSections:
    def test_ecg_keywords_detected(self):
        from app.services.document_classifier import detect_sections
        assert "ecg" in detect_sections(ECG_TEXT)

    def test_echo_keywords_detected(self):
        from app.services.document_classifier import detect_sections
        assert "echo" in detect_sections(ECHO_TEXT)

    def test_radiology_keywords_detected(self):
        from app.services.document_classifier import detect_sections
        assert "radiology" in detect_sections(RADIOLOGY_TEXT)

    def test_plain_lab_text_returns_empty(self):
        from app.services.document_classifier import detect_sections
        assert detect_sections(LAB_TEXT) == []

    def test_mixed_ecg_echo_both_detected(self):
        from app.services.document_classifier import detect_sections
        mixed = ECG_TEXT + "\n" + ECHO_TEXT
        sections = detect_sections(mixed)
        assert "ecg" in sections
        assert "echo" in sections

    def test_case_insensitive_matching(self):
        from app.services.document_classifier import detect_sections
        assert "ecg" in detect_sections("ELECTROCARDIOGRAM report QRS normal")
        assert "echo" in detect_sections("ejection fraction 55% LVEF measured")
        assert "radiology" in detect_sections("CT SCAN of chest no pneumothorax")

    def test_empty_text_returns_empty(self):
        from app.services.document_classifier import detect_sections
        assert detect_sections("") == []


class TestNeedsVisionTier:
    def test_too_few_lines_triggers_vision(self):
        from app.services.document_classifier import needs_vision_tier
        page = PageContent(page_num=1, lines=["Hb 12"], raw_text="Hb 12")
        assert needs_vision_tier(page) is True

    def test_sufficient_lines_does_not_trigger(self):
        from app.services.document_classifier import needs_vision_tier
        lines = LAB_TEXT.splitlines()
        page = PageContent(page_num=1, lines=lines, raw_text=LAB_TEXT)
        assert needs_vision_tier(page) is False

    def test_sparse_characters_triggers_vision(self):
        from app.services.document_classifier import needs_vision_tier
        lines = ["ab", "cd", "ef"]
        page = PageContent(page_num=1, lines=lines, raw_text="ab\ncd\nef")
        assert needs_vision_tier(page) is True

    def test_empty_page_triggers_vision(self):
        from app.services.document_classifier import needs_vision_tier
        page = PageContent(page_num=1, lines=[], raw_text="")
        assert needs_vision_tier(page) is True


class TestPickPrompt:
    def test_ecg_gets_ecg_prompt(self):
        from app.services.vision_providers.prompts import pick_prompt
        system, user = pick_prompt(["ecg"])
        assert "ECG" in system or "cardiology" in system.lower()
        assert "ECG" in user or "electrocardiogram" in user.lower()

    def test_echo_gets_echo_prompt(self):
        from app.services.vision_providers.prompts import pick_prompt
        system, user = pick_prompt(["echo"])
        assert "echocardiogram" in system.lower() or "cardiology" in system.lower()

    def test_radiology_gets_radiology_prompt(self):
        from app.services.vision_providers.prompts import pick_prompt
        system, user = pick_prompt(["radiology"])
        assert "radiology" in system.lower()

    def test_empty_sections_gets_general_prompt(self):
        from app.services.vision_providers.prompts import pick_prompt
        system, _user = pick_prompt([])
        assert "medical" in system.lower()

    def test_ecg_takes_priority_over_echo(self):
        from app.services.vision_providers.prompts import pick_prompt, _ECG_SYSTEM
        system, _ = pick_prompt(["ecg", "echo"])
        assert system == _ECG_SYSTEM

    def test_lab_sections_gets_lab_prompt(self):
        from app.services.vision_providers.prompts import pick_prompt
        _system, user = pick_prompt(["lab"])
        assert "lab" in user.lower() or "test result" in user.lower()


class TestOpenAIVisionProvider:
    def _make_mock_response(self, content: str):
        choice = MagicMock()
        choice.message.content = content
        response = MagicMock()
        response.choices = [choice]
        response.usage = MagicMock(prompt_tokens=200, completion_tokens=150)
        return response

    def test_ecg_extraction_returns_correct_lines(self):
        from app.services.vision_providers.openai_vision import OpenAIVisionProvider
        provider = OpenAIVisionProvider()
        mock_response = self._make_mock_response(ECG_TEXT)
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.vision_providers.openai_vision._get_client", return_value=mock_client):
            page = asyncio.run(provider.extract(_white_img(), ["ecg"], page_num=1))

        assert page.page_num == 1
        assert any("Heart Rate" in ln for ln in page.lines)
        assert any("sinus rhythm" in ln.lower() for ln in page.lines)

    def test_echo_extraction_returns_ef_line(self):
        from app.services.vision_providers.openai_vision import OpenAIVisionProvider
        provider = OpenAIVisionProvider()
        mock_response = self._make_mock_response(ECHO_TEXT)
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.vision_providers.openai_vision._get_client", return_value=mock_client):
            page = asyncio.run(provider.extract(_white_img(), ["echo"], page_num=2))

        assert any("EF" in ln for ln in page.lines)
        assert any("Mitral" in ln for ln in page.lines)

    def test_api_failure_returns_empty_page(self):
        from app.services.vision_providers.openai_vision import OpenAIVisionProvider
        provider = OpenAIVisionProvider()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API timeout"))

        with patch("app.services.vision_providers.openai_vision._get_client", return_value=mock_client):
            page = asyncio.run(provider.extract(_white_img(), ["ecg"], page_num=1))

        assert page.lines == []
        assert page.raw_text == ""

    def test_empty_model_response_returns_empty_page(self):
        from app.services.vision_providers.openai_vision import OpenAIVisionProvider
        provider = OpenAIVisionProvider()
        mock_response = self._make_mock_response("")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.vision_providers.openai_vision._get_client", return_value=mock_client):
            page = asyncio.run(provider.extract(_white_img(), [], page_num=1))

        assert page.lines == []

    def test_image_resize_applied_before_encoding(self):
        from app.services.vision_providers.openai_vision import _resize_image
        large = Image.new("RGB", (3000, 2000))
        resized = _resize_image(large, max_side=1024)
        assert max(resized.size) == 1024
        assert resized.size[0] / resized.size[1] == pytest.approx(3000 / 2000, rel=0.01)

    def test_small_image_not_upscaled(self):
        from app.services.vision_providers.openai_vision import _resize_image
        small = Image.new("RGB", (400, 300))
        result = _resize_image(small, max_side=1024)
        assert result.size == (400, 300)


class TestLocalVisionProvider:
    def _ollama_response(self, content: str) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": content}}
        resp.raise_for_status = MagicMock()
        return resp

    def test_lab_extraction_via_ollama(self):
        from app.services.vision_providers.local_vision import LocalVisionProvider
        provider = LocalVisionProvider()
        mock_resp = self._ollama_response(LAB_TEXT)

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.vision_providers.local_vision.httpx.AsyncClient", return_value=mock_http_client):
            page = asyncio.run(provider.extract(_white_img(), ["lab"], page_num=1))

        assert any("Haemoglobin" in ln for ln in page.lines)
        assert any("RBC" in ln for ln in page.lines)

    def test_ollama_connection_error_returns_empty_page(self):
        from app.services.vision_providers.local_vision import LocalVisionProvider
        provider = LocalVisionProvider()

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("app.services.vision_providers.local_vision.httpx.AsyncClient", return_value=mock_http_client):
            page = asyncio.run(provider.extract(_white_img(), ["ecg"], page_num=1))

        assert page.lines == []
        assert page.raw_text == ""

    def test_phi_compliance_no_external_call(self):
        """LocalVisionProvider must never call external OpenAI endpoints."""
        from app.services.vision_providers.local_vision import LocalVisionProvider
        provider = LocalVisionProvider()

        posted_urls = []
        mock_resp = self._ollama_response(ECG_TEXT)

        async def capture_post(url, **kwargs):
            posted_urls.append(url)
            return mock_resp

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = capture_post

        with patch("app.services.vision_providers.local_vision.httpx.AsyncClient", return_value=mock_http_client), \
             patch("app.core.config.settings.LOCAL_VISION_ENDPOINT", "http://localhost:11434"):
            asyncio.run(provider.extract(_white_img(), ["ecg"], page_num=1))

        assert all("openai.com" not in u for u in posted_urls)
        assert all("api.openai" not in u for u in posted_urls)


class TestVisionExtractor:
    def test_sync_wrapper_returns_page_content(self):
        from app.services import vision_extractor
        fake_page = PageContent(page_num=1, lines=["EF  55  %"], raw_text="EF  55  %")
        mock_provider = MagicMock()
        mock_provider.extract = AsyncMock(return_value=fake_page)

        with patch("app.services.vision_extractor.get_vision_provider", return_value=mock_provider):
            result = vision_extractor.extract_page_content(_white_img(), 1, ["echo"])

        assert result.lines == ["EF  55  %"]

    def test_provider_exception_returns_empty_page(self):
        from app.services import vision_extractor
        mock_provider = MagicMock()
        mock_provider.extract = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("app.services.vision_extractor.get_vision_provider", return_value=mock_provider):
            result = vision_extractor.extract_page_content(_white_img(), 1, ["ecg"])

        assert result.lines == []


class TestOcrVisionIntegration:
    """Integration tests: extract_pages routes to vision tier when appropriate."""

    def _make_pdf_mock(self, text: str = ""):
        page = MagicMock()
        page.extract_text.return_value = text
        pdf = MagicMock()
        pdf.pages = [page]
        pdf.__enter__ = MagicMock(return_value=pdf)
        pdf.__exit__ = MagicMock(return_value=False)
        return pdf

    def test_ecg_scanned_page_routed_to_vision(self):
        """Scanned ECG page must be promoted to vision tier."""
        from app.services import ocr

        ecg_page = PageContent(page_num=1, lines=ECG_TEXT.splitlines(), raw_text=ECG_TEXT)
        # Tesseract produces sparse output — vision kicks in
        sparse_tesseract = PageContent(page_num=1, lines=["ECG"], raw_text="ECG")
        fake_img = _white_img()

        with patch("app.services.ocr.pdfplumber.open", return_value=self._make_pdf_mock()), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="tesseract"), \
             patch("app.services.ocr._image_to_page_content", return_value=sparse_tesseract), \
             patch("app.services.ocr._vision_extract", return_value=ecg_page) as mock_vision:

            pages = ocr.extract_pages("ecg_report.pdf")

        mock_vision.assert_called_once()
        assert any("Heart Rate" in ln for ln in pages[0].lines)

    def test_degraded_page_triggers_vision(self):
        """A page with fewer than VISION_MIN_LINES lines must trigger vision."""
        from app.services import ocr

        sparse = PageContent(page_num=1, lines=["ab"], raw_text="ab")
        recovered = PageContent(page_num=1, lines=LAB_TEXT.splitlines(), raw_text=LAB_TEXT)
        fake_img = _white_img()

        with patch("app.services.ocr.pdfplumber.open", return_value=self._make_pdf_mock()), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="tesseract"), \
             patch("app.services.ocr._image_to_page_content", return_value=sparse), \
             patch("app.services.ocr._vision_extract", return_value=recovered) as mock_vision:

            pages = ocr.extract_pages("degraded.pdf")

        mock_vision.assert_called_once()
        assert any("Haemoglobin" in ln for ln in pages[0].lines)

    def test_good_tesseract_page_skips_vision(self):
        """A page with sufficient Tesseract output must NOT call vision."""
        from app.services import ocr

        good_lines = LAB_TEXT.splitlines()
        good_page = PageContent(page_num=1, lines=good_lines, raw_text=LAB_TEXT)
        fake_img = _white_img()

        with patch("app.services.ocr.pdfplumber.open", return_value=self._make_pdf_mock()), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="tesseract"), \
             patch("app.services.ocr._image_to_page_content", return_value=good_page), \
             patch("app.services.ocr._vision_extract") as mock_vision:

            ocr.extract_pages("lab_report.pdf")

        mock_vision.assert_not_called()

    def test_digital_pdf_always_skips_vision(self):
        """Pages with native text must never call classify_page or vision."""
        from app.services import ocr

        native_text = "Glucose  5.4  mmol/L  3.9-6.1\n" * 5

        with patch("app.services.ocr.pdfplumber.open", return_value=self._make_pdf_mock(native_text)), \
             patch("app.services.ocr._vision_extract") as mock_vision, \
             patch("app.services.ocr.classify_page") as mock_cls:

            pages = ocr.extract_pages("digital.pdf")

        mock_cls.assert_not_called()
        mock_vision.assert_not_called()
        assert "Glucose" in pages[0].raw_text

    def test_vision_disabled_skips_vision_call(self):
        """VISION_ENABLED=False must prevent any vision provider invocation."""
        from app.services import ocr

        sparse = PageContent(page_num=1, lines=["X"], raw_text="X")
        fake_img = _white_img()

        with patch("app.services.ocr.pdfplumber.open", return_value=self._make_pdf_mock()), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="tesseract"), \
             patch("app.services.ocr._image_to_page_content", return_value=sparse), \
             patch("app.core.config.settings.VISION_ENABLED", False):

            pages = ocr.extract_pages("disabled.pdf")

        assert pages[0].lines == ["X"]

    def test_section_tags_preserved_on_page(self):
        """detect_sections result must be stored in page.detected_sections."""
        from app.services import ocr

        ecg_ocr = PageContent(page_num=1, lines=["ECG", "Heart Rate  80  bpm"] * 3, raw_text=ECG_TEXT)
        fake_img = _white_img()

        with patch("app.services.ocr.pdfplumber.open", return_value=self._make_pdf_mock()), \
             patch("app.services.ocr.convert_from_path", return_value=[fake_img]), \
             patch("app.services.ocr.classify_page", return_value="tesseract"), \
             patch("app.services.ocr._image_to_page_content", return_value=ecg_ocr), \
             patch("app.services.ocr._vision_extract", return_value=ecg_ocr):

            pages = ocr.extract_pages("ecg.pdf")

        assert "ecg" in pages[0].detected_sections
