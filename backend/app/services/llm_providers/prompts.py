"""
Shared prompt templates and JSON utilities used by all LLM providers.

Keeps prompt engineering in one place — providers just call
``build_messages()`` and ``parse_or_repair_json()``.
"""

import json
import re
from typing import Optional, List

from app.core.logging import get_logger

logger = get_logger("llm.prompt")

MAX_RAW_CHARS = 8000  # truncate raw_text before sending to LLM

_SCHEMA_OBJ = {
    "disclaimer": "string",
    "input_summary": {
        "document_type": "string",
        "detected_language": "string",
        "detected_hospital": "string|null",
        "date_of_report": "string|null",
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
            "dietary_recommendations": ["string"],
        }
    ],
    "urgency_level": "routine|soon|urgent|emergency",
    "red_flags": ["string — symptom that needs immediate attention"],
    "normal_values": [
        {
            "test_name": "string",
            "value": "string",
            "normal_range": "string",
            "what_it_means": "string",
        }
    ],
    "medicines": [
        {
            "name": "string",
            "generic_name": "string|null — official INN generic name",
            "purpose": "string",
            "mechanism": "string — how the drug works in 1-2 simple sentences",
            "how_to_take": "string|null",
            "common_side_effects": ["string"],
            "serious_side_effects": ["string"],
            "drug_interactions": ["string"],
            "precautions": ["string"],
            "generic_alternative": "string|null — cheaper Indian generic brand name",
            "lifestyle_tips": ["string"],
            "cost_saving_tip": "string|null — practical India-specific tip to save cost",
        }
    ],
    "overall_summary": "string",
    "questions_to_ask_doctor": ["string"],
    "next_steps": ["string"],
    "confidence_score": "number",
}

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
  A blood report may have 10-20 tests — list ALL of them.
- CLASSIFICATION RULE (strict): Compare each value against its reference range.
  If the value is ABOVE the max OR BELOW the min of the normal range → put it
  in abnormal_values. ONLY put a test in normal_values if the value falls
  strictly within the normal range. Never put a high or low result in
  normal_values, even if it is only slightly out of range.
- For each abnormal value, provide specific causes and actionable advice.
- For each medicine, explain purpose and side effects in plain language.
- If data is truly insufficient for a field, use null or empty array [].
- confidence_score: 0.0-1.0 reflecting how much usable data was found.
  Set to 1.0 if raw_text was readable and all tests were extracted.
- DOCUMENT TYPE RULE (critical — follow strictly):
  * If the document is a PRESCRIPTION / DOCTOR'S Rx (contains medicines prescribed by
    a doctor, not lab test numerical results), then:
    • abnormal_values MUST be [] — prescriptions contain dosages, NOT lab values.
      Never put "1 tablet", "60000 IU", dosage amounts etc. into abnormal_values.
    • normal_values MUST be [] for the same reason.
    • Focus all effort on the medicines array — list every prescribed drug.
  * If the document is a BLOOD REPORT / LAB REPORT / DIAGNOSTIC REPORT, then:
    • Extract ALL numerical lab test results into abnormal_values or normal_values.
    • Do NOT confuse medicine dosages (tablet, capsule, IU) with lab test values.
- MEDICINE FIELDS RULE — use your medical knowledge, never leave these null:
  * generic_name: official INN name (e.g. "Atorvastatin" for Lipitor).
    If the drug name IS already generic, repeat it here.
  * mechanism: how this drug works — 1-2 sentences in plain patient language.
  * generic_alternative: a common cheaper Indian brand with dose
    (e.g. "Atorva 20mg by Cadila", "Glycomet 500mg by USV").
  * cost_saving_tip: one practical India-specific tip (Jan Aushadhi stores,
    splitting tablets if safe, asking for generic prescription, etc.).

Always follow this JSON schema exactly:
{{SCHEMA}}
"""

SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.replace(
    "{{SCHEMA}}", json.dumps(_SCHEMA_OBJ, separators=(",", ":"))
)

def build_messages(
    parsed_data: dict,
    retrieval_context: Optional[List[str]] = None,
) -> list:
    """Return [system, user] message list for the LLM.
    RAG chunks are injected into the user message when provided.
    """
    safe_parsed = json.loads(json.dumps(parsed_data))
    raw_text = safe_parsed.get("raw_text")
    if isinstance(raw_text, str) and len(raw_text) > MAX_RAW_CHARS:
        safe_parsed["raw_text"] = raw_text[:MAX_RAW_CHARS] + "…"

    enriched_payload = {"parsed_data": safe_parsed}

    # RAG context block
    rag_block = ""
    if retrieval_context:
        chunks = "\n---\n".join(retrieval_context)
        rag_block = (
            "\n\nRelevant medical knowledge (use as authoritative reference "
            "for explaining test results, medicines, and recommendations):\n"
            f"```\n{chunks}\n```\n"
        )

    user_prompt = (
        "Analyse the medical document below and return a JSON object "
        "matching the required schema.\n\n"
        f"Input data (includes raw OCR text AND pre-extracted structured fields):\n"
        f"{json.dumps(enriched_payload, separators=(',', ':'))}\n"
        f"{rag_block}\n"
        "Instructions:\n"
        "- Use raw_text as the PRIMARY source — extract every test, value, "
        "medicine, hospital, doctor, and date from it.\n"
        "- Use the structured fields (tests/medicines) as hints, not the only source.\n"
        "- Return ONLY JSON. No explanations, no markdown.\n"
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def parse_or_repair_json(text: str) -> dict:
    """Parse LLM output as JSON, with several repair heuristics.

    Handles:
      1. Clean JSON.
      2. JSON wrapped in markdown fences (```json ... ```).
      3. JSON buried inside prose — extract first { … last }.
      4. Truncated output detection.
    """
    text = text.strip()

    # 1. Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. Strip markdown fences (```json … ```)
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except Exception:
            pass

    # 3. Extract first { … last }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(text[first : last + 1])
        except Exception:
            pass

    # 4. Truncation detection
    if not text.endswith("}"):
        raise RuntimeError("LLM output truncated (likely token limit)")

    raise RuntimeError("LLM returned invalid JSON after repair")


def validate_schema(data: dict):
    """Lightweight check that required top-level keys exist."""
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
