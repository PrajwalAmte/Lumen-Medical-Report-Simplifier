import pytest
from unittest.mock import patch, AsyncMock
from app.services.llm import generate_explanation, generate_explanation_async


GOOD_RESPONSE = {
    "disclaimer": "test",
    "input_summary": {
        "document_type": "blood_report",
        "detected_language": "en",
        "detected_hospital": None,
        "date_of_report": None,
    },
    "abnormal_values": [],
    "normal_values": [],
    "medicines": [],
    "overall_summary": "Test summary",
    "questions_to_ask_doctor": [],
    "next_steps": [],
    "confidence_score": 0.85,
    "urgency_level": "routine",
    "red_flags": [],
}


def _mock_provider(return_value=None, side_effect=None):
    """Create a mock LLMProvider whose generate() returns given data."""
    provider = AsyncMock()
    if side_effect:
        provider.generate.side_effect = side_effect
    else:
        provider.generate.return_value = return_value or GOOD_RESPONSE
    return provider


@pytest.mark.asyncio
@patch("app.services.llm.get_provider")
async def test_generate_explanation_success(mock_get_provider):
    mock_get_provider.return_value = _mock_provider(GOOD_RESPONSE)

    parsed_data = {"tests": [{"name": "Hemoglobin", "value": 12.5, "is_abnormal": True}]}
    result = await generate_explanation_async(parsed_data)

    assert result is not None
    assert "overall_summary" in result
    assert result["overall_summary"] == "Test summary"


@pytest.mark.asyncio
@patch("app.services.llm.get_provider")
async def test_generate_explanation_empty_input(mock_get_provider):
    """Empty input should still return a dict (LLM gets empty parsed data)."""
    empty_response = dict(GOOD_RESPONSE, overall_summary="No data", confidence_score=0.0)
    mock_get_provider.return_value = _mock_provider(empty_response)

    result = await generate_explanation_async({})

    assert result is not None
    assert isinstance(result, dict)


@pytest.mark.asyncio
@patch("app.services.llm.get_provider")
async def test_generate_explanation_llm_failure(mock_get_provider):
    """All retries exhaust → should return a fallback dict, not raise."""
    mock_get_provider.return_value = _mock_provider(
        side_effect=Exception("LLM down")
    )

    result = await generate_explanation_async({"tests": []})

    assert result is not None
    assert isinstance(result, dict)
    assert result.get("confidence_score", 0) < 0.5


@pytest.mark.asyncio
@patch("app.services.llm.get_provider")
async def test_generate_explanation_with_retrieval_context(mock_get_provider):
    """Retrieval context is forwarded to the provider."""
    mock_prov = _mock_provider(GOOD_RESPONSE)
    mock_get_provider.return_value = mock_prov

    ctx = ["Hemoglobin is a protein in red blood cells."]
    await generate_explanation_async({"tests": []}, retrieval_context=ctx)

    mock_prov.generate.assert_called_once()
    call_args = mock_prov.generate.call_args
    assert call_args[0][1] == ctx


@pytest.mark.asyncio
@patch("app.services.llm.get_provider")
async def test_generate_explanation_retries(mock_get_provider):
    """Provider fails once then succeeds — retry logic works."""
    mock_prov = AsyncMock()
    mock_prov.generate.side_effect = [
        Exception("transient error"),
        GOOD_RESPONSE,
    ]
    mock_get_provider.return_value = mock_prov

    result = await generate_explanation_async({"tests": []})

    assert result is not None
    assert result.get("overall_summary") == "Test summary"
    assert mock_prov.generate.call_count == 2


def test_generate_explanation_sync():
    """Sync wrapper delegates correctly."""
    with patch("app.services.llm.get_provider") as mock_get_provider:
        mock_get_provider.return_value = _mock_provider(GOOD_RESPONSE)
        result = generate_explanation({"tests": []})
        assert result is not None
        assert isinstance(result, dict)
    assert isinstance(result, dict)


class TestBuildMessages:
    """Unit tests for the Phase 5 build_messages function."""

    def test_no_raw_text_in_payload(self):
        """raw_text must never appear in the user message sent to the LLM."""
        from app.services.llm_providers.prompts import build_messages

        parsed = {
            "tests": [{"id": "hb", "name": "Haemoglobin", "value": 9.0,
                        "unit": "g/dL", "normal_min": 13.0, "normal_max": 17.0,
                        "is_abnormal": True, "extraction_confidence": 0.95,
                        "extraction_tier": "digital_text", "validator_note": ""}],
            "medicines": [],
            "extraction_artifacts": [],
            "detected_sections": [],
            "document_summary": {"avg_confidence": 0.95, "total_tests": 1},
            "raw_text": "Haemoglobin 9.0 g/dL",
        }
        messages = build_messages(parsed)
        user_content = messages[1]["content"]
        assert "raw_text" not in user_content

    def test_structured_fields_present(self):
        """tests, medicines, detected_sections, document_summary must be in the payload."""
        from app.services.llm_providers.prompts import build_messages

        parsed = {
            "tests": [{"id": "hb", "name": "Haemoglobin", "value": 9.0,
                        "unit": "g/dL", "normal_min": 13.0, "normal_max": 17.0,
                        "is_abnormal": True, "extraction_confidence": 0.95,
                        "extraction_tier": "digital_text", "validator_note": ""}],
            "medicines": [{"id": "atorva", "name": "Atorvastatin", "category": "statin"}],
            "extraction_artifacts": [],
            "detected_sections": ["ecg"],
            "document_summary": {"avg_confidence": 0.95, "total_tests": 1},
        }
        messages = build_messages(parsed)
        user_content = messages[1]["content"]
        assert "Haemoglobin" in user_content
        assert "Atorvastatin" in user_content
        assert "ecg" in user_content
        assert "avg_confidence" in user_content

    def test_rag_block_injected(self):
        """RAG context chunks must appear in the user message."""
        from app.services.llm_providers.prompts import build_messages

        messages = build_messages({}, retrieval_context=["Haemoglobin reference text."])
        assert "Haemoglobin reference text." in messages[1]["content"]

    def test_system_message_is_explanation_only(self):
        """System prompt must mention explanation role, not extraction."""
        from app.services.llm_providers.prompts import build_messages, SYSTEM_PROMPT

        assert "EXPLANATION ONLY" in SYSTEM_PROMPT
        assert "extraction_confidence" in SYSTEM_PROMPT
        assert "is_abnormal" in SYSTEM_PROMPT
        # Must NOT instruct the model to extract from raw text
        assert "Extract EVERY test result from raw_text" not in SYSTEM_PROMPT

    def test_is_abnormal_flag_passed_through(self):
        """is_abnormal flag must appear in the serialized payload."""
        from app.services.llm_providers.prompts import build_messages
        import json

        parsed = {
            "tests": [{"id": "gluc", "value": 12.0, "is_abnormal": True,
                        "extraction_confidence": 0.99, "validator_note": ""}],
        }
        messages = build_messages(parsed)
        payload_str = messages[1]["content"]
        assert "is_abnormal" in payload_str

    def test_confidence_levels_in_system_prompt(self):
        """System prompt must contain the three confidence thresholds."""
        from app.services.llm_providers.prompts import SYSTEM_PROMPT

        assert "0.90" in SYSTEM_PROMPT or ">= 0.90" in SYSTEM_PROMPT or ">= 0.9" in SYSTEM_PROMPT
        assert "0.70" in SYSTEM_PROMPT or "0.7" in SYSTEM_PROMPT
        assert "< 0.70" in SYSTEM_PROMPT or "< 0.7" in SYSTEM_PROMPT


class TestExtractionToParsedData:
    """Unit tests for the refactored processor._extraction_to_parsed_data."""

    def _make_extraction_result(self):
        from app.models.extraction import ExtractionResult, ExtractedValue, ExtractedMedicine

        v_passed = ExtractedValue(
            test_id="haemoglobin", raw_name="Haemoglobin",
            raw_value="9.5", value_numeric=9.5, unit="g/dL",
            ref_range_raw="13-17", ref_min=13.0, ref_max=17.0,
            source_page=1, source_line="Haemoglobin  9.5  g/dL",
            extraction_tier="digital_text",
            validator_status="passed", confidence=0.97,
        )
        v_flagged = ExtractedValue(
            test_id="glucose", raw_name="Glucose",
            raw_value="4.1", value_numeric=4.1, unit="mmol/L",
            ref_range_raw="4.0-6.0", ref_min=4.0, ref_max=6.0,
            source_page=1, source_line="Glucose  4.1  mmol/L",
            extraction_tier="paddle_table",
            validator_status="flagged", validator_note="Near lower limit",
            confidence=0.72,
        )
        v_rejected = ExtractedValue(
            test_id="rbc", raw_name="RBC",
            raw_value="999", value_numeric=999.0, unit="M/uL",
            ref_range_raw="4.5-5.5", ref_min=4.5, ref_max=5.5,
            source_page=1, source_line="RBC  999",
            extraction_tier="tesseract",
            validator_status="rejected", validator_note="Hard limit exceeded",
            confidence=0.40,
        )
        m = ExtractedMedicine(
            id="atorva", name="Atorvastatin", category="statin",
            source_page=1, source_line="Tab Atorvastatin 20mg",
        )
        result = ExtractionResult(
            values=[v_passed, v_flagged, v_rejected],
            medicines=[m],
            extraction_tier="digital_text",
        )
        return result

    def _make_pages(self, sections=None):
        from app.models.extraction import PageContent
        return [
            PageContent(page_num=1, lines=["test"], raw_text="test",
                        detected_sections=sections or [])
        ]

    def test_raw_text_absent_from_output(self):
        from app.workers.processor import _extraction_to_parsed_data
        result = _extraction_to_parsed_data(self._make_extraction_result(), self._make_pages())
        assert "raw_text" not in result

    def test_rejected_values_go_to_artifacts_not_tests(self):
        from app.workers.processor import _extraction_to_parsed_data
        data = _extraction_to_parsed_data(self._make_extraction_result(), self._make_pages())
        test_ids = [t["id"] for t in data["tests"]]
        artifact_ids = [a["test_id"] for a in data["extraction_artifacts"]]
        assert "rbc" not in test_ids
        assert "rbc" in artifact_ids

    def test_is_abnormal_correctly_set(self):
        from app.workers.processor import _extraction_to_parsed_data
        data = _extraction_to_parsed_data(self._make_extraction_result(), self._make_pages())
        hb = next(t for t in data["tests"] if t["id"] == "haemoglobin")
        gluc = next(t for t in data["tests"] if t["id"] == "glucose")
        assert hb["is_abnormal"] is True
        assert gluc["is_abnormal"] is False

    def test_confidence_score_in_each_test(self):
        from app.workers.processor import _extraction_to_parsed_data
        data = _extraction_to_parsed_data(self._make_extraction_result(), self._make_pages())
        for test in data["tests"]:
            assert "extraction_confidence" in test
            assert 0.0 <= test["extraction_confidence"] <= 1.0

    def test_document_summary_avg_confidence(self):
        from app.workers.processor import _extraction_to_parsed_data
        data = _extraction_to_parsed_data(self._make_extraction_result(), self._make_pages())
        summary = data["document_summary"]
        assert "avg_confidence" in summary
        assert isinstance(summary["avg_confidence"], float)
        assert 0.0 <= summary["avg_confidence"] <= 1.0

    def test_detected_sections_aggregated_from_pages(self):
        from app.workers.processor import _extraction_to_parsed_data
        pages = self._make_pages(sections=["ecg", "radiology"])
        data = _extraction_to_parsed_data(self._make_extraction_result(), pages)
        assert "ecg" in data["detected_sections"]
        assert "radiology" in data["detected_sections"]

    def test_detected_sections_deduplicated(self):
        from app.models.extraction import PageContent
        from app.workers.processor import _extraction_to_parsed_data
        pages = [
            PageContent(page_num=1, lines=[], raw_text="", detected_sections=["ecg"]),
            PageContent(page_num=2, lines=[], raw_text="", detected_sections=["ecg", "echo"]),
        ]
        data = _extraction_to_parsed_data(self._make_extraction_result(), pages)
        assert data["detected_sections"].count("ecg") == 1

    def test_validator_note_passed_for_flagged_only(self):
        from app.workers.processor import _extraction_to_parsed_data
        data = _extraction_to_parsed_data(self._make_extraction_result(), self._make_pages())
        gluc = next(t for t in data["tests"] if t["id"] == "glucose")
        hb = next(t for t in data["tests"] if t["id"] == "haemoglobin")
        assert gluc["validator_note"] == "Near lower limit"
        assert hb["validator_note"] == ""

    def test_document_summary_counts(self):
        from app.workers.processor import _extraction_to_parsed_data
        data = _extraction_to_parsed_data(self._make_extraction_result(), self._make_pages())
        summary = data["document_summary"]
        assert summary["total_tests"] == 2
        assert summary["total_medicines"] == 1
        assert summary["rejected_values"] == 1
