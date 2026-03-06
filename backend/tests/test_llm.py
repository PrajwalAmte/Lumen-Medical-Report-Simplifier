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

    parsed_data = {"tests": [{"name": "Hemoglobin", "value": "12.5"}]}
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
    # Fallback has low confidence
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
    assert call_args[0][1] == ctx  # second positional arg


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
