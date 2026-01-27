from typing import Any, Dict, List


def _ensure_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return str(x)
    if isinstance(x, str):
        return x.strip()
    return default


def _ensure_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def sanitize_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize result payload so it NEVER violates ResultResponse schema.
    Safe to run multiple times (idempotent).
    """

    if not isinstance(data, dict):
        data = {}

    data["disclaimer"] = _ensure_str(data.get("disclaimer"), "")
    data["overall_summary"] = _ensure_str(data.get("overall_summary"), "No data available")

    for v in data.get("normal_values", []):
        v.pop("severity", None)

    try:
        data["confidence_score"] = float(data.get("confidence_score", 0.0))
    except Exception:
        data["confidence_score"] = 0.0

    data["abnormal_values"] = _ensure_list(data.get("abnormal_values"))
    data["normal_values"] = _ensure_list(data.get("normal_values"))
    data["medicines"] = _ensure_list(data.get("medicines"))
    data["questions_to_ask_doctor"] = _ensure_list(data.get("questions_to_ask_doctor"))
    data["next_steps"] = _ensure_list(data.get("next_steps"))

    data["pattern_analysis"] = data.get("pattern_analysis") or None
    urg = _ensure_str(data.get("urgency_level"), "").lower()
    data["urgency_level"] = urg if urg in {"routine", "soon", "urgent", "emergency"} else None
    data["lifestyle_action_plan"] = data.get("lifestyle_action_plan") or None
    data["red_flags"] = _ensure_list(data.get("red_flags"))

    metadata = data.get("metadata") or {}
    try:
        metadata["processing_time_sec"] = int(metadata.get("processing_time_sec", 0))
    except Exception:
        metadata["processing_time_sec"] = 0
    metadata["ocr_engine"] = _ensure_str(metadata.get("ocr_engine"), "unknown")
    metadata["llm_provider"] = _ensure_str(metadata.get("llm_provider"), "unknown")
    metadata["model"] = _ensure_str(metadata.get("model"), "unknown")
    metadata["cached"] = bool(metadata.get("cached", False))
    data["metadata"] = metadata

    input_summary = data.get("input_summary") or {}
    input_summary["document_type"] = _ensure_str(input_summary.get("document_type"), "unknown")
    input_summary["detected_language"] = _ensure_str(input_summary.get("detected_language"), "unknown")

    input_summary["detected_hospital"] = input_summary.get("detected_hospital")
    input_summary["date_of_report"] = input_summary.get("date_of_report")
    data["input_summary"] = input_summary

    def _sanitize_test_entry(e: Any, abnormal: bool) -> Dict[str, Any]:
        if not isinstance(e, dict):
            e = {}

        base = {
            "test_name": _ensure_str(e.get("test_name"), "Unknown"),
            "value": _ensure_str(e.get("value"), ""),
            "normal_range": _ensure_str(e.get("normal_range"), ""),
            "what_it_means": _ensure_str(e.get("what_it_means"), ""),
        }

        if abnormal:
            sev = _ensure_str(e.get("severity"), "mild").lower()
            allowed = {"mild", "moderate", "severe", "critical", "low", "high", "unknown"}
            base["severity"] = sev if sev in allowed else "unknown"
            base["common_causes"] = _ensure_list(e.get("common_causes"))
            base["what_to_ask_doctor"] = _ensure_list(e.get("what_to_ask_doctor"))

            base["health_risks"] = _ensure_list(e.get("health_risks"))
            base["lifestyle_recommendations"] = _ensure_list(e.get("lifestyle_recommendations"))
            base["dietary_recommendations"] = _ensure_list(e.get("dietary_recommendations"))

        return base

    data["abnormal_values"] = [
        _sanitize_test_entry(e, True) for e in data.get("abnormal_values", [])
    ]

    data["normal_values"] = [
        _sanitize_test_entry(e, False) for e in data.get("normal_values", [])
    ]

    meds_out: List[Dict[str, Any]] = []
    for m in data.get("medicines", []):
        if not isinstance(m, dict):
            m = {}

        meds_out.append({
            "name": _ensure_str(m.get("name"), "Unknown"),
            "generic_name": m.get("generic_name"),
            "purpose": _ensure_str(m.get("purpose"), "Prescribed by your doctor."),
            "mechanism": _ensure_str(m.get("mechanism"), None) if m.get("mechanism") is not None else None,
            "how_to_take": _ensure_str(m.get("how_to_take"), None) if m.get("how_to_take") is not None else None,
            "common_side_effects": _ensure_list(m.get("common_side_effects"))[:3],
            "serious_side_effects": _ensure_list(m.get("serious_side_effects"))[:3],
            "drug_interactions": _ensure_list(m.get("drug_interactions"))[:3],
            "precautions": _ensure_list(m.get("precautions"))[:3],
            "generic_alternative": m.get("generic_alternative"),
            "lifestyle_tips": _ensure_list(m.get("lifestyle_tips"))[:3],
            "cost_saving_tip": _ensure_str(m.get("cost_saving_tip"), None) if m.get("cost_saving_tip") is not None else None,
        })

    data["medicines"] = meds_out
    try:
        data["confidence_score"] = float(data.get("confidence_score", 0.0))
    except Exception:
        data["confidence_score"] = 0.0

    return data
