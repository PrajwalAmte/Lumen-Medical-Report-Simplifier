import pytest
from unittest.mock import Mock, patch
from app.services.llm import generate_explanation


@patch('app.services.llm.OpenAI')
def test_generate_explanation_success(mock_openai):
    mock_client = Mock()
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = '{"overall_summary": "Test summary", "confidence_score": 0.85}'
    
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai.return_value = mock_client
    
    parsed_data = {"tests": [{"name": "Hemoglobin", "value": "12.5"}]}
    
    result = generate_explanation(parsed_data)
    
    assert result is not None
    assert "overall_summary" in result


def test_generate_explanation_empty_input():
    result = generate_explanation({})
    
    assert result is not None
    assert isinstance(result, dict)