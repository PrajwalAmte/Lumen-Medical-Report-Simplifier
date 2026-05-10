"""
Shared prompt templates and JSON utilities used by all LLM providers.

Keeps prompt engineering in one place — providers just call
``build_messages()`` and ``parse_or_repair_json()``.

Phase 5 refactor — explanation-only role:
  The LLM no longer receives raw OCR text or is asked to re-extract values.
  Extraction is fully handled by the 3-tier pipeline (digital / PaddleOCR /
  vision LLM).  This module's job is to build a clean structured payload and
  a prompt that turns validated, classified test data into patient-friendly
  explanations.
"""

import json
import re
from typing import Optional, List

from app.core.logging import get_logger

logger = get_logger("llm.prompt")

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
            "value": "string — copy EXACTLY from the provided value + unit fields",
            "normal_range": "string — copy EXACTLY from normal_min and normal_max",
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

SYSTEM_PROMPT = """You are Lumen, a medical report explainer for Indian patients.

Your role is EXPLANATION ONLY. The structured data you receive has already been \
extracted and validated by a multi-tier OCR pipeline. Do not attempt to \
re-extract or reinterpret numerical values — work exclusively with the \
structured fields provided.

Output rules:
- Output ONLY valid JSON matching the schema. No markdown, no commentary.
- Do NOT omit any required keys. Do NOT add extra keys.
- Use simple Indian English that a non-medical person can understand.
- Never invent medical facts not supported by the provided data.

Classification rule:
- Each test carries an is_abnormal flag computed by clinical validation.
  Tests where is_abnormal=true go into abnormal_values.
  Tests where is_abnormal=false go into normal_values.
- Copy value and normal_range exactly from the provided fields — \
  do not reformat numbers or change units.

Confidence-aware explanation:
- extraction_confidence is a 0.0–1.0 quality score from the extraction pipeline.
  >= 0.90: high confidence — explain directly.
  0.70–0.89: moderate confidence — add "Please confirm this value by checking \
your original report." at the end of what_it_means.
  < 0.70: low confidence — add "This value had low extraction confidence. \
Verify against your original report before acting on it." at the end of \
what_it_means.
- If validator_note is non-empty, include it verbatim at the start of \
  what_it_means, followed by your explanation.

Severity rule (for abnormal values):
- Compare value against normal_min / normal_max using the percentage deviation.
  > 50% deviation: critical. > 30%: severe. > 15%: moderate. Otherwise: mild.

Special sections:
- detected_sections lists medical section types found in the document
  (possible values: ecg, echo, radiology).
  ecg: use appropriate cardiology/electrocardiography language.
  echo: explain ejection fraction, chamber dimensions, valve findings accessibly.
  radiology: explain radiographic findings in plain language.

Medicines:
- Use your medical knowledge for mechanism, generic_name, generic_alternative, \
  and cost_saving_tip.
- generic_alternative: name a common Indian brand with dose \
  (e.g. "Atorva 20mg by Cadila").
- cost_saving_tip: one India-specific practical tip \
  (Jan Aushadhi stores, asking for a generic prescription, etc.).

confidence_score: use document_summary.avg_confidence from the input. \
If no tests were found, set to 0.0.

Always follow this JSON schema exactly:
""" + json.dumps(_SCHEMA_OBJ, separators=(",", ":"))


def build_messages(
    parsed_data: dict,
    retrieval_context: Optional[List[str]] = None,
) -> list:
    """
    Build the [system, user] message list for the LLM.

    The payload sent to the LLM contains ONLY structured fields — no raw OCR
    text.  Each test includes its pre-computed is_abnormal flag and
    extraction_confidence so the LLM can apply confidence-aware explanation
    without having to perform its own extraction or classification.

    RAG chunks are injected into the user message when provided.
    """
    safe = json.loads(json.dumps(parsed_data))

    tests = safe.get("tests", [])
    for t in tests:
        t.pop("raw_text", None)

    payload = {
        "tests":                tests,
        "medicines":            safe.get("medicines", []),
        "extraction_artifacts": safe.get("extraction_artifacts", []),
        "detected_sections":    safe.get("detected_sections", []),
        "document_summary":     safe.get("document_summary", {}),
    }

    rag_block = ""
    if retrieval_context:
        chunks = "\n---\n".join(retrieval_context)
        rag_block = (
            "\n\nRelevant medical knowledge (use as authoritative reference "
            "for explaining test results, medicines, and recommendations):\n"
            f"```\n{chunks}\n```\n"
        )

    user_prompt = (
        "Explain the following pre-extracted and validated medical data. "
        "Return a JSON object matching the required schema.\n\n"
        f"Structured extraction data:\n"
        f"{json.dumps(payload, separators=(',', ':'))}\n"
        f"{rag_block}\n"
        "Return ONLY JSON. No explanations, no markdown."
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

    try:
        return json.loads(text)
    except Exception:
        pass

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except Exception:
            pass

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(text[first : last + 1])
        except Exception:
            pass

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
