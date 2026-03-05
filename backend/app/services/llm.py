import json
import asyncio
import time
from typing import Optional, List, Any, Dict

from openai import OpenAI, AsyncOpenAI
from app.core.config import settings
from app.core.logging import get_logger
from app.services.catalog import TEST_CATALOG, MEDICINE_CATALOG
from app.services.result_sanitizer import sanitize_result

logger = get_logger("llm")
client = OpenAI(api_key=settings.OPENAI_API_KEY)
async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# Maximum characters of raw text to send to LLM to prevent token overflow.
# gpt-4.1-mini supports 128k context; 8000 chars ≈ 2000 tokens, well within budget.
MAX_RAW_CHARS = 8000

# System prompt template that enforces strict JSON output format
SYSTEM_PROMPT_TEMPLATE = """
You are Lumen, a medical report explainer for Indian patients.

Rules:
- Output ONLY valid JSON. No markdown, no commentary.
- Do NOT omit any required keys. Do NOT add extra keys.
- Never invent medical facts. Base everything on the provided data.
- Use simple Indian English that a non-medical person can understand.
- UNIT RULE: Copy values and units EXACTLY as written in the document.
  Never convert, infer, or substitute units. If the document says
  "12,800 cells/uL", output value="12800 cells/uL". Commas in numbers
  are thousands separators — "12,800" means twelve thousand eight hundred.
- Extract EVERY test result from raw_text. Do NOT stop after the first few.
  A blood report may have 10-20 tests — list ALL of them in abnormal_values
  or normal_values as appropriate.
- Compare each test value against its normal range to decide if abnormal.
- For each abnormal value, provide specific causes and actionable advice.
- For each medicine, explain purpose and side effects in plain language.
- If data is truly insufficient for a field, use null or empty array [].
- confidence_score: 0.0-1.0 reflecting how much usable data was found.
  Set to 1.0 if raw_text was readable and all tests were extracted.

Always follow this JSON schema exactly:
{{SCHEMA}}
"""

# Expected response schema for medical explanations
_SCHEMA_OBJ = {
    "disclaimer": "string",
    "input_summary": {
        "document_type": "string",
        "detected_language": "string",
        "detected_hospital": "string|null",
        "date_of_report": "string|null"
    },
    "abnormal_values": [
        {
            "test_name": "string",
            "value": "string — copy EXACTLY from document including unit",
            "normal_range": "string — copy EXACTLY from document",
            "severity": "mild|moderate|severe|critical",
            "what_it_means": "string — plain English explanation",
            "common_causes": ["string"],
            "what_to_ask_doctor": ["string"],
            "health_risks": ["string"],
            "lifestyle_recommendations": ["string"],
            "dietary_recommendations": ["string"]
        }
    ],
    "urgency_level": "routine|soon|urgent|emergency",
    "red_flags": ["string — symptom that needs immediate attention"],
    "normal_values": [
        {
            "test_name": "string",
            "value": "string",
            "normal_range": "string",
            "what_it_means": "string"
        }
    ],
    "medicines": [
        {
            "name": "string",
            "generic_name": "string|null",
            "purpose": "string",
            "mechanism": "string|null",
            "how_to_take": "string|null",
            "common_side_effects": ["string"],
            "serious_side_effects": ["string"],
            "drug_interactions": ["string"],
            "precautions": ["string"],
            "generic_alternative": "string|null",
            "lifestyle_tips": ["string"]
        }
    ],
    "overall_summary": "string",
    "questions_to_ask_doctor": ["string"],
    "next_steps": ["string"],
    "confidence_score": "number"
}

# Complete system prompt with embedded schema
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.replace(
    "{{SCHEMA}}", json.dumps(_SCHEMA_OBJ, separators=(",", ":"))
)


def generate_explanation(parsed_data: dict) -> dict:
    """Generate medical explanation with retry logic and fallback.
    
    Args:
        parsed_data: Structured medical data from parser
        
    Returns:
        dict: Medical explanation following the schema
    """
    for attempt in range(1, settings.LLM_RETRY_COUNT + 1):
        try:
            logger.info(f"LLM attempt {attempt}/{settings.LLM_RETRY_COUNT}")
            return _call_openai(parsed_data)
        except Exception as e:
            logger.warning(f"LLM attempt {attempt} failed: {e}")
            if attempt < settings.LLM_RETRY_COUNT:
                # Exponential backoff with maximum 8 seconds
                time.sleep(min(settings.LLM_RETRY_BACKOFF_SEC * attempt, 8))
            else:
                logger.error("All LLM attempts failed. Using fallback.")
                return _fallback_explanation(parsed_data)


def _call_openai(parsed_data: dict) -> dict:
    """Make actual call to OpenAI API with structured data."""
    # Ensure data is JSON serializable by round-trip conversion
    safe_parsed = json.loads(json.dumps(parsed_data))  

    raw_text = safe_parsed.get("raw_text")
    if isinstance(raw_text, str) and len(raw_text) > MAX_RAW_CHARS:
        safe_parsed["raw_text"] = raw_text[:MAX_RAW_CHARS] + "…"

    enriched_payload = {
        "parsed_data": safe_parsed
    }

    user_prompt = f"""
Analyse the medical document below and return a JSON object matching the required schema.

Input data (includes raw OCR text AND pre-extracted structured fields):
{json.dumps(enriched_payload, separators=(",", ":"))}

Instructions:
- Use raw_text as the PRIMARY source — extract every test, value, medicine, hospital, doctor, and date from it.
- Use the structured fields (tests/medicines) as hints, not the only source.
- Return ONLY JSON. No explanations, no markdown.
"""

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=0.0,
        timeout=settings.LLM_TIMEOUT_SEC,
        response_format={"type": "json_object"},
    )

    output_text = (response.choices[0].message.content or "").strip()
    logger.info(f"Raw LLM output length={len(output_text)}")

    usage = getattr(response, "usage", None)
    if usage:
        logger.info(
            f"LLM token usage — prompt={usage.prompt_tokens}, "
            f"completion={usage.completion_tokens}, total={usage.total_tokens}"
        )

    if not output_text:
        raise RuntimeError("Empty response from LLM")

    parsed_json = _parse_or_repair_json(output_text)
    parsed_json = sanitize_result(parsed_json)
    _validate_schema(parsed_json)

    return parsed_json


# ---------------------------------------------------------------------------
#  Async variants — used by the async worker pipeline (#20)
# ---------------------------------------------------------------------------

async def generate_explanation_async(parsed_data: dict) -> dict:
    """Async version of generate_explanation with retry + fallback."""
    for attempt in range(1, settings.LLM_RETRY_COUNT + 1):
        try:
            logger.info(f"Async LLM attempt {attempt}/{settings.LLM_RETRY_COUNT}")
            return await _call_openai_async(parsed_data)
        except Exception as e:
            logger.warning(f"Async LLM attempt {attempt} failed: {e}")
            if attempt < settings.LLM_RETRY_COUNT:
                await asyncio.sleep(min(settings.LLM_RETRY_BACKOFF_SEC * attempt, 8))
            else:
                logger.error("All async LLM attempts failed. Using fallback.")
                return _fallback_explanation(parsed_data)


async def _call_openai_async(parsed_data: dict) -> dict:
    """Async OpenAI call — uses the AsyncOpenAI client so the event-loop
    is not blocked while waiting for the network response."""
    safe_parsed = json.loads(json.dumps(parsed_data))

    raw_text = safe_parsed.get("raw_text")
    if isinstance(raw_text, str) and len(raw_text) > MAX_RAW_CHARS:
        safe_parsed["raw_text"] = raw_text[:MAX_RAW_CHARS] + "…"

    enriched_payload = {"parsed_data": safe_parsed}

    user_prompt = f"""
Analyse the medical document below and return a JSON object matching the required schema.

Input data (includes raw OCR text AND pre-extracted structured fields):
{json.dumps(enriched_payload, separators=(",", ":"))}

Instructions:
- Use raw_text as the PRIMARY source — extract every test, value, medicine, hospital, doctor, and date from it.
- Use the structured fields (tests/medicines) as hints, not the only source.
- Return ONLY JSON. No explanations, no markdown.
"""

    response = await async_client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=0.0,
        timeout=settings.LLM_TIMEOUT_SEC,
        response_format={"type": "json_object"},
    )

    output_text = (response.choices[0].message.content or "").strip()
    logger.info(f"Async LLM output length={len(output_text)}")

    usage = getattr(response, "usage", None)
    if usage:
        logger.info(
            f"LLM token usage — prompt={usage.prompt_tokens}, "
            f"completion={usage.completion_tokens}, total={usage.total_tokens}"
        )

    if not output_text:
        raise RuntimeError("Empty response from async LLM")

    parsed_json = _parse_or_repair_json(output_text)
    parsed_json = sanitize_result(parsed_json)
    _validate_schema(parsed_json)

    return parsed_json


def _parse_or_repair_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception as e:
        logger.warning(f"JSON parse failed, attempting repair: {e}")

        first = text.find("{")
        last = text.rfind("}")

        if first != -1 and last != -1 and last > first:
            try:
                return json.loads(text[first:last + 1])
            except Exception:
                pass

        if not text.strip().endswith("}"):
            raise RuntimeError("LLM output truncated (likely token limit)")


        raise RuntimeError("LLM returned invalid JSON after repair")


def _validate_schema(data: dict):
    required_keys = [
        "disclaimer",
        "input_summary",
        "abnormal_values",
        "normal_values",
        "medicines",
        "overall_summary",
        "questions_to_ask_doctor",
        "next_steps",
        "confidence_score",
    ]

    for key in required_keys:
        if key not in data:
            raise RuntimeError(f"LLM response missing key: {key}")

    if not isinstance(data["confidence_score"], (int, float)):
        raise RuntimeError("confidence_score must be a number")


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
            "what_to_ask_doctor": enriched["questions"]
        }

        if enriched["is_abnormal"]:
            abnormal_values.append(entry)
        else:
            normal_values.append(entry)

    medicine_blocks = _fallback_medicines(medicines)

    result = {
        "disclaimer": "This explanation is automated and not a medical diagnosis. Always consult your doctor.",
        "input_summary": {
            "document_type": "medical_report",
            "detected_language": "en",
            "detected_hospital": None,
            "date_of_report": None
        },
        "abnormal_values": abnormal_values,
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
    direction = None  # "low" or "high" — preserved for downstream context

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

        # Map deviation percentage to clinical severity.
        # direction is kept separate so both pieces of information survive.
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
        direction_label = f"({'below' if direction == 'low' else 'above'} normal)"
        meaning = catalog.get("meaning") or f"This value is outside the normal range {direction_label}."
    else:
        meaning = catalog.get("normal_meaning") or "This value is within the normal range."

    causes = catalog.get("common_causes", [])
    questions = []

    if is_abnormal:
        level_word = "low" if direction == "low" else "high"
        questions = [
            f"What is causing my {level_word} {name} result?",
            f"Is my {name} level serious at this range?",
            f"Do I need further tests for {name}?",
            f"What lifestyle changes can help improve my {name}?"
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
        "questions": questions
    }


def _fallback_medicines(medicines: list) -> list:
    blocks = []

    for m in medicines:
        med_id = m.get("id") if isinstance(m, dict) else None
        catalog = MEDICINE_CATALOG.get(med_id, {})

        name = catalog.get("display_name") or (m.get("name") if isinstance(m, dict) else str(m))

        blocks.append({
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
        })

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
