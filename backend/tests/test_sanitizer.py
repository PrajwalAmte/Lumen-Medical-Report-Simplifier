import pytest
from app.services.result_sanitizer import sanitize_result, _ensure_str, _ensure_list


# ---------- _ensure_str ----------

class TestEnsureStr:
    def test_none(self):
        assert _ensure_str(None) == ""

    def test_none_with_default(self):
        assert _ensure_str(None, "fallback") == "fallback"

    def test_int(self):
        assert _ensure_str(42) == "42"

    def test_float(self):
        assert _ensure_str(3.14) == "3.14"

    def test_string_strips(self):
        assert _ensure_str("  hello  ") == "hello"

    def test_list_returns_default(self):
        assert _ensure_str([1, 2]) == ""


# ---------- _ensure_list ----------

class TestEnsureList:
    def test_none(self):
        assert _ensure_list(None) == []

    def test_already_list(self):
        assert _ensure_list([1, 2]) == [1, 2]

    def test_scalar_wraps(self):
        assert _ensure_list("single") == ["single"]


# ---------- sanitize_result ----------

class TestSanitizeResult:
    def test_empty_dict(self):
        result = sanitize_result({})
        assert result["disclaimer"] == ""
        assert result["overall_summary"] == "No data available"
        assert result["abnormal_values"] == []
        assert result["normal_values"] == []
        assert result["medicines"] == []
        assert result["confidence_score"] == 0.0
        assert result["metadata"]["ocr_engine"] == "unknown"
        assert result["input_summary"]["document_type"] == "unknown"

    def test_non_dict_input(self):
        result = sanitize_result("bad input")
        assert isinstance(result, dict)
        assert result["overall_summary"] == "No data available"

    def test_preserves_valid_data(self):
        data = {
            "disclaimer": "Test",
            "overall_summary": "Everything is fine",
            "confidence_score": 0.92,
            "urgency_level": "routine",
            "abnormal_values": [],
            "normal_values": [],
            "medicines": [],
            "questions_to_ask_doctor": [],
            "next_steps": [],
            "red_flags": [],
            "metadata": {
                "processing_time_sec": 12,
                "ocr_engine": "tesseract",
                "llm_provider": "groq",
                "model": "llama-3.3",
                "cached": False,
            },
            "input_summary": {
                "document_type": "blood_report",
                "detected_language": "en",
            },
        }
        result = sanitize_result(data)
        assert result["disclaimer"] == "Test"
        assert result["confidence_score"] == 0.92
        assert result["urgency_level"] == "routine"
        assert result["metadata"]["processing_time_sec"] == 12

    def test_invalid_urgency_normalised(self):
        data = {"urgency_level": "CRITICAL_DANGER"}
        result = sanitize_result(data)
        assert result["urgency_level"] is None

    def test_valid_urgencies(self):
        for level in ("routine", "soon", "urgent", "emergency"):
            data = {"urgency_level": level}
            result = sanitize_result(data)
            assert result["urgency_level"] == level

    def test_confidence_score_string_coerced(self):
        result = sanitize_result({"confidence_score": "0.75"})
        assert result["confidence_score"] == 0.75

    def test_confidence_score_garbage(self):
        result = sanitize_result({"confidence_score": "not-a-number"})
        assert result["confidence_score"] == 0.0

    def test_abnormal_value_sanitised(self):
        data = {
            "abnormal_values": [
                {
                    "test_name": "Cholesterol",
                    "value": "250",
                    "normal_range": "<200",
                    "severity": "high",
                }
            ]
        }
        result = sanitize_result(data)
        av = result["abnormal_values"][0]
        assert av["test_name"] == "Cholesterol"
        assert av["severity"] == "high"
        assert "common_causes" in av
        assert "what_to_ask_doctor" in av

    def test_abnormal_value_bad_severity(self):
        data = {
            "abnormal_values": [
                {"test_name": "X", "severity": "BANANA"}
            ]
        }
        result = sanitize_result(data)
        assert result["abnormal_values"][0]["severity"] == "unknown"

    def test_normal_value_strips_severity(self):
        data = {
            "normal_values": [
                {"test_name": "Hb", "value": "14", "normal_range": "12-16", "severity": "high"}
            ]
        }
        result = sanitize_result(data)
        nv = result["normal_values"][0]
        assert "severity" not in nv

    def test_medicine_sanitised(self):
        data = {
            "medicines": [
                {
                    "name": "Metformin",
                    "purpose": "Diabetes",
                    "common_side_effects": ["Nausea", "Diarrhea", "Vomiting", "Headache"],
                }
            ]
        }
        result = sanitize_result(data)
        med = result["medicines"][0]
        assert med["name"] == "Metformin"
        # Capped at 3
        assert len(med["common_side_effects"]) == 3

    def test_medicine_non_dict_entry(self):
        data = {"medicines": ["not a dict"]}
        result = sanitize_result(data)
        assert result["medicines"][0]["name"] == "Unknown"

    def test_idempotent(self):
        data = {"overall_summary": "Test", "confidence_score": 0.5}
        pass1 = sanitize_result(data)
        pass2 = sanitize_result(pass1)
        assert pass1 == pass2

    def test_metadata_defaults(self):
        result = sanitize_result({"metadata": None})
        assert result["metadata"]["processing_time_sec"] == 0
        assert result["metadata"]["cached"] is False
