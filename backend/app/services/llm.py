"""
LLM service — public API surface for the rest of the application.

All provider-specific logic now lives in ``llm_providers/``.
This module provides:
  • ``generate_explanation_async(parsed_data, retrieval_context)``
  • ``generate_explanation(parsed_data)``

Retry + fallback logic is kept here (business logic, not provider detail).
"""

import asyncio
from typing import Optional, List

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_providers import get_provider
from app.services.catalog import TEST_CATALOG, MEDICINE_CATALOG
from app.services.result_sanitizer import sanitize_result

logger = get_logger("llm")


# ── Public API (async-only) ───────────────────────────────────────────

async def generate_explanation_async(
    parsed_data: dict,
    retrieval_context: Optional[List[str]] = None,
) -> dict:
    """Generate medical explanation with retry + fallback.

    This is the ONLY public entry point.  The sync wrapper
    ``generate_explanation()`` below calls this via ``asyncio.run()``.

    Parameters
    ----------
    parsed_data : dict
        Output from the parser (tests, medicines, raw_text).
    retrieval_context : list[str], optional
        RAG chunks retrieved from the vector store.
    """
    provider = get_provider()

    for attempt in range(1, settings.LLM_RETRY_COUNT + 1):
        try:
            logger.info(
                f"LLM attempt {attempt}/{settings.LLM_RETRY_COUNT} "
                f"(provider={settings.LLM_PROVIDER})"
            )
            result = await provider.generate(parsed_data, retrieval_context)
            return result
        except Exception as e:
            logger.warning(f"LLM attempt {attempt} failed: {e}")
            if attempt < settings.LLM_RETRY_COUNT:
                await asyncio.sleep(
                    min(settings.LLM_RETRY_BACKOFF_SEC * attempt, 8)
                )
            else:
                logger.error("All LLM attempts failed. Using fallback.")
                return _fallback_explanation(parsed_data)


def generate_explanation(parsed_data: dict) -> dict:
    """Sync wrapper — delegates to the async implementation."""
    return asyncio.run(generate_explanation_async(parsed_data))


# ── Fallback (rule-based, no LLM) ────────────────────────────────────

def _fallback_explanation(parsed_data: dict) -> dict:
    tests = parsed_data.get("tests", [])
    medicines = parsed_data.get("medicines", [])

    abnormal_values = []
    normal_values = []
    enriched_tests = []

    for t in tests:
        enriched = _enrich_test_with_catalog(t)
        enriched_tests.append(enriched)

        entry = {
            "test_name": enriched["name"],
            "value": enriched["value_str"],
            "normal_range": enriched["normal_range_str"],
            "severity": enriched["severity"],
            "what_it_means": enriched["meaning"],
            "common_causes": enriched["common_causes"],
            "what_to_ask_doctor": enriched["questions"],
        }

        if enriched["is_abnormal"]:
            abnormal_values.append(entry)
        else:
            normal_values.append(entry)

    medicine_blocks = _fallback_medicines(medicines)

    result = {
        "disclaimer": (
            "This explanation is automated and not a medical diagnosis. "
            "Always consult your doctor."
        ),
        "input_summary": {
            "document_type": "medical_report",
            "detected_language": "en",
            "detected_hospital": None,
            "date_of_report": None,
        },
        "abnormal_values": abnormal_values,
        "urgency_level": "routine",
        "red_flags": [],
        "normal_values": normal_values,
        "medicines": medicine_blocks,
        "overall_summary": (
            f"{len(abnormal_values)} value(s) are outside the normal range."
            if abnormal_values
            else "All detected values are within normal ranges."
        ),
        "questions_to_ask_doctor": _build_questions_from_tests(enriched_tests),
        "next_steps": _build_next_steps_from_tests(enriched_tests),
        "confidence_score": 0.25,
    }

    return sanitize_result(result)


# ── Catalog enrichment helpers ────────────────────────────────────────

def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None


def _enrich_test_with_catalog(t: dict) -> dict:
    test_id = t.get("id")
    catalog = TEST_CATALOG.get(test_id, {})

    value = _safe_float(t.get("value"))
    min_v = _safe_float(t.get("normal_min"))
    max_v = _safe_float(t.get("normal_max"))

    is_abnormal = False
    severity = "unknown"
    direction = None

    if value is not None and min_v is not None and max_v is not None:
        if value < min_v:
            deviation = ((min_v - value) / min_v) * 100 if min_v != 0 else 0
            is_abnormal = True
            direction = "low"
        elif value > max_v:
            deviation = ((value - max_v) / max_v) * 100 if max_v != 0 else 0
            is_abnormal = True
            direction = "high"
        else:
            deviation = 0

        if is_abnormal:
            if deviation > 50:
                severity = "critical"
            elif deviation > 30:
                severity = "severe"
            elif deviation > 15:
                severity = "moderate"
            else:
                severity = "mild"

    name = catalog.get("display_name") or t.get("name") or "Unknown"
    unit = t.get("unit", "")
    value_str = f"{t.get('value')} {unit}".strip()
    normal_range_str = (
        f"{min_v}–{max_v} {unit}".strip()
        if min_v is not None and max_v is not None
        else "Not available"
    )

    if is_abnormal:
        direction_label = (
            f"({'below' if direction == 'low' else 'above'} normal)"
        )
        meaning = (
            catalog.get("meaning")
            or f"This value is outside the normal range {direction_label}."
        )
    else:
        meaning = (
            catalog.get("normal_meaning")
            or "This value is within the normal range."
        )

    causes = catalog.get("common_causes", [])
    questions = []

    if is_abnormal:
        level_word = "low" if direction == "low" else "high"
        questions = [
            f"What is causing my {level_word} {name} result?",
            f"Is my {name} level serious at this range?",
            f"Do I need further tests for {name}?",
            f"What lifestyle changes can help improve my {name}?",
        ]

    return {
        "id": test_id,
        "name": name,
        "value_str": value_str,
        "normal_range_str": normal_range_str,
        "severity": severity,
        "direction": direction,
        "is_abnormal": is_abnormal,
        "meaning": meaning,
        "common_causes": causes,
        "questions": questions,
    }


def _fallback_medicines(medicines: list) -> list:
    blocks = []

    for m in medicines:
        med_id = m.get("id") if isinstance(m, dict) else None
        catalog = MEDICINE_CATALOG.get(med_id, {})

        name = catalog.get("display_name") or (
            m.get("name") if isinstance(m, dict) else str(m)
        )

        blocks.append(
            {
                "name": name,
                "generic_name": catalog.get("generic_name"),
                "purpose": catalog.get("purpose") or "Prescribed by your doctor.",
                "mechanism": catalog.get("mechanism"),
                "how_to_take": catalog.get("how_to_take"),
                "common_side_effects": catalog.get("common_side_effects", [])[:3],
                "serious_side_effects": catalog.get("serious_side_effects", [])[:3],
                "drug_interactions": catalog.get("drug_interactions", [])[:3],
                "precautions": catalog.get("precautions", [])[:3],
                "generic_alternative": catalog.get("generic_alternative"),
                "lifestyle_tips": catalog.get("lifestyle_tips", [])[:3],
            }
        )

    return blocks


def _build_questions_from_tests(tests: List[dict]) -> List[str]:
    questions = []
    for t in tests:
        if t["is_abnormal"]:
            questions.extend(t["questions"])
    return list(dict.fromkeys(questions))[:8]


def _build_next_steps_from_tests(tests: List[dict]) -> List[str]:
    steps = []
    abnormal = [t for t in tests if t["is_abnormal"]]

    if abnormal:
        steps.append("Consult your doctor within 1–2 weeks")
        if any(t["severity"] in {"severe", "critical"} for t in abnormal):
            steps.append("Seek medical advice urgently")
        steps.append("Repeat abnormal tests if advised")
    else:
        steps.append("Continue healthy habits")
        steps.append("Repeat routine tests in 6–12 months")

    return steps
