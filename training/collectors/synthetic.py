"""
Synthetic Indian medical report generator.

Supports two providers (pass provider= to collect()):
  "groq"   — free tier; uses Groq's OpenAI-compatible endpoint.
             OCR: llama-3.1-8b-instant  (high RPD, fast)
             Structured input + explanation: llama-3.3-70b-versatile
  "openai" — paid; gpt-4o-mini for OCR/structured, gpt-4o for explanation.

Generates:
  (A) DAPT text  — realistic OCR-style Indian lab report text for domain training.
  (B) SFT pairs  — (pre-validated structured input → explanation JSON) pairs for
                   fine-tuning the model as a pure EXPLAINER, not an extractor.

Architecture alignment:
  OCR → parser → validator → [fine-tuned explainer model]
  SFT input is clean validated data (what the validator produces), NOT raw OCR text.

Two LLM calls per SFT pair:
  1. _generate_structured_input  — simulates deterministic pipeline output
  2. _generate_explanation_json  — generates Lumen explanation JSON from that input
DAPT uses one call (OCR text generation).

Outputs:
  - dapt_output  : JSONL with {"text": ..., "source": "synthetic_report", "profile": {...}}
  - sft_output   : JSONL with {"conversations": [...], "sft_format": "explainer_v2", ...}
                   (chat format — directly usable with Unsloth SFTTrainer)
"""

import json
import random
import re
import time
from pathlib import Path

from openai import OpenAI, RateLimitError, APIError

# ---------------------------------------------------------------------------
# Provider config — model names and base URLs
# ---------------------------------------------------------------------------
_PROVIDER_CONFIGS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        # All three calls use 8b-instant: 20,000 TPM vs 70b's 6,000 TPM.
        # 70b is too constrained on the free tier — one explanation call alone
        # (~4500 tokens) saturates the 6k TPM bucket and triggers cascading
        # rate-limit retries. 8b-instant handles structured JSON + explanation
        # well enough for synthetic training-data generation.
        "ocr_model":         "llama-3.1-8b-instant",
        "structured_model":  "llama-3.1-8b-instant",
        "explanation_model": "llama-3.1-8b-instant",
    },
    "openai": {
        "base_url": None,                # default OpenAI endpoint
        "ocr_model":         "gpt-4o-mini",
        "structured_model":  "gpt-4o-mini",
        "explanation_model": "gpt-4o",
    },
}

# ---------------------------------------------------------------------------
# Retry helper — exponential backoff on rate limits
# Works with both OpenAI and Groq clients (both raise openai.RateLimitError
# when using the openai library pointed at Groq's base URL).
# ---------------------------------------------------------------------------
_MAX_RETRIES = 5
_RETRY_BASE_WAIT = 10  # seconds; doubles each attempt: 10, 20, 40, 80, 160


class DailyQuotaError(Exception):
    """Raised when the provider's daily token/request quota is exhausted.
    Retrying is pointless — the quota resets at midnight UTC."""


def _is_daily_quota(exc: RateLimitError) -> bool:
    """Return True if the 429 is a daily quota error (not a per-minute spike)."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ("per day", "daily", "tokens per day", "requests per day", "tpd", "rpd"))


def _call_with_retry(fn, label: str):
    """
    Call fn() and retry up to _MAX_RETRIES times on per-minute RateLimitError,
    doubling the wait each time.

    Raises DailyQuotaError immediately if the 429 indicates a daily limit —
    retrying is useless in that case and the caller should exit gracefully.

    Returns the result, or None on repeated per-minute failures.
    """
    wait = _RETRY_BASE_WAIT
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except RateLimitError as e:
            if _is_daily_quota(e):
                raise DailyQuotaError(str(e))
            if attempt == _MAX_RETRIES:
                print(f"    [{label}] Rate limited {_MAX_RETRIES}x — giving up on this item.")
                return None
            print(f"    [{label}] Rate limited — waiting {wait}s (attempt {attempt}/{_MAX_RETRIES})...")
            time.sleep(wait)
            wait = min(wait * 2, 960)
        except APIError as e:
            print(f"    [{label}] API error: {e}")
            return None
    return None

from .utils import append_jsonl

# ---------------------------------------------------------------------------
# Patient profile pool — realistic Indian demographic variation
# ---------------------------------------------------------------------------
AGES = list(range(22, 72))
GENDERS = ["male", "female"]
CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad", "Kolkata",
    "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Patna", "Bhopal",
    "Nagpur", "Coimbatore", "Kochi", "Chandigarh", "Indore", "Surat",
]
LABS = [
    "Thyrocare Technologies",
    "SRL Diagnostics",
    "Dr. Lal PathLabs",
    "Metropolis Healthcare",
    "Apollo Diagnostics",
    "AIIMS Clinical Biochemistry Lab",
    "Manipal Hospital Lab",
    "Fortis Healthcare Laboratory",
    "Suburban Diagnostics",
    "Vijaya Diagnostic Centre",
]
REFERRING_DOCTORS = [
    "Dr. Suresh Mehta, MD (General Medicine)",
    "Dr. Priya Krishnan, MBBS, DNB (Family Medicine)",
    "Dr. Rajiv Sharma, MD (Internal Medicine)",
    "Dr. Anita Desai, DM (Endocrinology)",
    "Dr. Vijay Nair, MD (Cardiology)",
    "Dr. Sunita Rao, MBBS (General Practitioner)",
]

# ---------------------------------------------------------------------------
# Clinical scenarios — each has a panel and a range of realistic conditions
# ---------------------------------------------------------------------------
SCENARIOS = [
    {
        "panel": "Complete Blood Count (CBC) / Haemogram",
        "conditions": [
            "normal healthy adult",
            "iron deficiency anaemia — low Hb, low MCV, low MCH",
            "elevated WBC suggesting bacterial infection",
            "thrombocytopenia with low platelet count",
            "megaloblastic anaemia — high MCV, low Hb",
            "polycythaemia — elevated Hb and RBC",
            "dengue fever pattern — low platelets, slightly low WBC",
        ],
    },
    {
        "panel": "Liver Function Tests (LFT)",
        "conditions": [
            "normal LFT",
            "elevated SGPT/ALT — non-alcoholic fatty liver disease (NAFLD)",
            "obstructive jaundice pattern — high direct bilirubin, high ALP",
            "hepatocellular damage — high SGOT and SGPT",
            "hepatitis B pattern — markedly elevated transaminases",
            "alcoholic liver disease — AST:ALT ratio > 2",
        ],
    },
    {
        "panel": "Kidney Function Tests (KFT) / Renal Profile",
        "conditions": [
            "normal renal function",
            "mildly elevated creatinine — CKD stage 2",
            "significantly elevated creatinine and urea — CKD stage 4",
            "acute kidney injury pattern",
            "diabetic nephropathy — elevated creatinine with proteinuria",
            "normal creatinine with electrolyte imbalance",
        ],
    },
    {
        "panel": "Lipid Profile (Fasting)",
        "conditions": [
            "normal fasting lipid profile",
            "isolated high LDL cholesterol",
            "hypertriglyceridaemia — very high triglycerides",
            "mixed dyslipidaemia — high LDL, high TG, low HDL",
            "low HDL cholesterol with metabolic syndrome pattern",
        ],
    },
    {
        "panel": "Thyroid Function Tests (TFT) — TSH, Free T3, Free T4",
        "conditions": [
            "euthyroid — normal thyroid function",
            "primary hypothyroidism — very high TSH, low Free T4",
            "subclinical hypothyroidism — mildly elevated TSH, normal Free T4",
            "hyperthyroidism — suppressed TSH, elevated Free T3 and T4",
            "subclinical hyperthyroidism — low TSH, normal T3/T4",
        ],
    },
    {
        "panel": "Blood Glucose + HbA1c",
        "conditions": [
            "normal fasting blood glucose and HbA1c",
            "prediabetes — impaired fasting glucose, HbA1c 5.7–6.4%",
            "well-controlled Type 2 diabetes — HbA1c 6.5–7.0%",
            "poorly controlled Type 2 diabetes — HbA1c > 9%",
            "newly detected diabetes — very high fasting glucose, HbA1c > 10%",
        ],
    },
    {
        "panel": "Complete Haemogram + Peripheral Blood Smear",
        "conditions": [
            "normal peripheral smear",
            "microcytic hypochromic anaemia — iron deficiency pattern on smear",
            "malaria — Plasmodium vivax ring forms on smear",
            "megaloblastic — hypersegmented neutrophils on smear",
        ],
    },
    {
        "panel": "Urine Routine and Microscopy (Urinalysis)",
        "conditions": [
            "normal urine routine",
            "urinary tract infection — pus cells, bacteria present",
            "diabetic nephropathy — proteinuria, microalbuminuria",
            "renal calculi — haematuria, calcium oxalate crystals",
            "nephrotic syndrome — heavy proteinuria, lipid droplets",
        ],
    },
    {
        "panel": "Doctor's Prescription (Rx)",
        "conditions": [
            "hypertension management — amlodipine, telmisartan, aspirin",
            "Type 2 diabetes management — metformin, glimepiride, januvia",
            "post-MI prescription — clopidogrel, atorvastatin, ramipril, aspirin",
            "hypothyroidism — levothyroxine, calcium supplement",
            "respiratory infection — azithromycin, montelukast, paracetamol",
            "anaemia treatment — ferrous sulfate, folic acid, vitamin C",
        ],
    },
]

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
_OCR_PROMPT = """\
Generate realistic OCR-extracted text from an Indian medical report with these details:

Patient: {age}-year-old {gender} from {city}
Lab / Hospital: {lab}
Referring Doctor: {doctor}
Test Panel: {panel}
Clinical Scenario: {condition}

Requirements:
- Format exactly as a real {lab} printed report — include header with lab name/address/phone,
  patient demographics section, accession/barcode number, collection and report dates.
- Present results as a table-like layout with columns: TEST NAME | RESULT | UNIT | REFERENCE RANGE
- Use realistic Indian lab reference ranges (ICMR / lab-specific).
- Include all standard tests in this panel with plausible numerical values for the scenario.
- For prescriptions: format as a doctor's Rx pad with patient name, date, drug name, dose, \
frequency, duration, advice.
- Use Indian English terminology (haemoglobin not hemoglobin, colour not color, etc.).
- Add minor OCR artefacts: occasional extra spaces, hyphen at line breaks, abbreviated column headers.
- End with doctor's signature line, lab director name, and disclaimer text typical of Indian labs.

Output only the raw report text — no commentary, no markdown fences.\
"""

# ---------------------------------------------------------------------------
# Explainer system prompt — used as the system turn in all SFT conversations.
# The fine-tuned model receives pre-validated structured data as input and
# generates explanation JSON only.  Keep this in sync with the explainer
# provider's system prompt when deploying the fine-tuned model in production.
# ---------------------------------------------------------------------------
EXPLAINER_SYSTEM_PROMPT = """\
You are Lumen, a medical report explainer for Indian patients.

You receive pre-validated, pre-extracted structured lab results produced by a \
deterministic medical pipeline. Your ONLY task is to generate patient-friendly \
explanations, causes, advice, and summaries in simple Indian English.

STRICT RULES:
- Output ONLY valid JSON matching the schema below. No markdown, no commentary.
- NEVER re-extract, re-derive, or override the values or severity labels in the input.
  Copy test_name, value, unit, ref_range, and severity EXACTLY from the structured input.
- NEVER invent test results, values, or medicines not present in the structured input.
- All explanatory text must use simple Indian English for a non-medical person.
- For medicines: explain purpose, side effects, and cost-saving alternatives (Indian market).
- urgency_level must reflect the highest severity in the input:
  borderline → routine | mild → soon | moderate → soon | severe → urgent | critical → emergency
- confidence_score: 1.0 when all inputs are recognised and explained; 0.8–0.9 only if some
  test names are unrecognised.

REQUIRED OUTPUT SCHEMA (all keys required; use [] or null for empty fields):
{
  "disclaimer": "string",
  "input_summary": {
    "document_type": "string",
    "detected_language": "string",
    "detected_hospital": "string|null",
    "date_of_report": "string|null"
  },
  "abnormal_values": [{
    "test_name": "string — copy from input",
    "value": "string — copy value+unit from input",
    "normal_range": "string — constructed from ref_min/ref_max in input",
    "severity": "borderline|mild|moderate|severe|critical — copy from input",
    "what_it_means": "string",
    "common_causes": ["string"],
    "what_to_ask_doctor": ["string"],
    "health_risks": ["string"],
    "lifestyle_recommendations": ["string"],
    "dietary_recommendations": ["string"]
  }],
  "urgency_level": "routine|soon|urgent|emergency",
  "red_flags": ["string"],
  "normal_values": [{
    "test_name": "string",
    "value": "string",
    "normal_range": "string",
    "what_it_means": "string"
  }],
  "medicines": [{
    "name": "string",
    "generic_name": "string|null",
    "purpose": "string",
    "mechanism": "string",
    "how_to_take": "string|null",
    "common_side_effects": ["string"],
    "serious_side_effects": ["string"],
    "drug_interactions": ["string"],
    "precautions": ["string"],
    "generic_alternative": "string|null",
    "lifestyle_tips": ["string"],
    "cost_saving_tip": "string|null"
  }],
  "overall_summary": "string",
  "questions_to_ask_doctor": ["string"],
  "next_steps": ["string"],
  "confidence_score": number
}"""

# Prompt used to simulate the output of the deterministic extraction pipeline.
# Uses .format(**profile) — JSON braces are doubled to escape them.
_STRUCTURED_INPUT_PROMPT = """\
Simulate the output of a deterministic Indian medical report parsing pipeline for:

Patient: {age}-year-old {gender} from {city}
Lab / Hospital: {lab}
Referring Doctor: {doctor}
Test Panel: {panel}
Clinical Scenario: {condition}

Generate a JSON object representing pre-validated, pre-extracted results exactly as a \
rule-based medical validator would produce. A fine-tuned LLM will receive this as its \
sole input and generate patient-friendly explanations from it — it will NOT see raw OCR text.

Severity classification rules (deterministic, based on % deviation from reference range):
- below_normal: ≤10% below ref_min → borderline | 10–25% → mild | 25–50% → moderate
  >50% below or clinically dangerous threshold → severe or critical
- above_normal: ≤20% above ref_max → borderline | 20–50% → mild | 50–100% → moderate
  >100% above or clinically dangerous threshold → severe or critical
- Within reference range → status=normal, severity=normal
- For prescription documents: validated_tests=[], list all prescribed medicines.

Output ONLY this JSON — no commentary, no markdown fences:
{{
  "validated_tests": [
    {{
      "test_name": "string — standard ICMR/Indian lab name",
      "value": number,
      "unit": "string",
      "ref_min": number,
      "ref_max": number,
      "status": "normal|above_normal|below_normal",
      "severity": "normal|borderline|mild|moderate|severe|critical"
    }}
  ],
  "medicines": [
    {{"name": "string — drug name with strength", "dosage": "string"}}
  ],
  "document_metadata": {{
    "document_type": "lab_report|prescription|radiology_report",
    "hospital": "string",
    "date_of_report": "string",
    "patient_age": number,
    "patient_gender": "male|female",
    "referring_doctor": "string"
  }}
}}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _build_ocr_prompt(profile: dict) -> str:
    return _OCR_PROMPT.format(**profile)


def _generate_ocr_text(client: OpenAI, profile: dict, model: str) -> str | None:
    """Generate synthetic OCR-style report text. Returns None on failure."""
    def _call():
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _build_ocr_prompt(profile)}],
            max_tokens=1800,
            temperature=0.85,
        )
        return resp.choices[0].message.content.strip()
    return _call_with_retry(_call, "OCR")


def _generate_structured_input(client: OpenAI, profile: dict, model: str) -> dict | None:
    """
    Simulate the output of the deterministic Lumen extraction pipeline for a
    given clinical scenario.  Returns a dict with validated_tests, medicines,
    and document_metadata, or None on failure.
    """
    prompt = _STRUCTURED_INPUT_PROMPT.format(**profile)

    def _call():
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()

    raw = _call_with_retry(_call, "structured-input")
    if raw is None:
        return None
    # Strip markdown fences if the model wraps JSON despite instructions
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"    Structured input not valid JSON — {e}")
        return None


def _generate_explanation_json(
    client: OpenAI,
    structured_input: dict,
    explainer_system_prompt: str,
    model: str,
) -> str | None:
    """
    Generate Lumen explanation JSON from pre-validated structured input.
    Values, units, and severity labels must be copied verbatim — enforced by
    the system prompt.  Returns the raw JSON string, or None on failure.
    """
    user_content = (
        "Explain these pre-validated lab results to an Indian patient in simple language.\n\n"
        f"Pre-validated results:\n"
        f"{json.dumps(structured_input, ensure_ascii=False, indent=2)}\n\n"
        "Generate the full explanation JSON. Use the provided values, units, ref ranges, "
        "and severity classifications EXACTLY — do not re-derive or modify them.\n"
        "Return ONLY JSON."
    )

    def _call():
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": explainer_system_prompt},
                {"role": "user",   "content": user_content},
            ],
            max_tokens=3000,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()

    raw = _call_with_retry(_call, "explanation")
    if raw is None:
        return None
    # Llama/Groq wraps JSON in markdown fences despite instructions — strip them
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())
    return raw


def _build_profile() -> dict:
    scenario = random.choice(SCENARIOS)
    return {
        "age": random.choice(AGES),
        "gender": random.choice(GENDERS),
        "city": random.choice(CITIES),
        "lab": random.choice(LABS),
        "doctor": random.choice(REFERRING_DOCTORS),
        "panel": scenario["panel"],
        "condition": random.choice(scenario["conditions"]),
    }


def collect(
    dapt_output: Path,
    sft_output: Path,
    count: int,
    api_key: str,
    provider: str = "groq",
    system_prompt: str | None = None,
    generate_sft: bool = True,
) -> tuple[int, int]:
    """
    Generate `count` synthetic Indian lab reports.

    For each report:
      1. Generate OCR-style text → DAPT record (always).
      2. Generate structured validated input (simulating deterministic pipeline output)
         → generate explanation JSON from it → SFT chat pair (if generate_sft=True).

    SFT pairs train the model as a pure EXPLAINER: input is pre-validated structured
    data, never raw OCR text.

    Args:
        dapt_output:  Path to write DAPT JSONL records.
        sft_output:   Path to write SFT chat-format JSONL records.
        count:        Number of reports to generate.
        api_key:      API key for the chosen provider.
        provider:     "groq" (free, default) or "openai".
        system_prompt: Explainer system prompt; defaults to EXPLAINER_SYSTEM_PROMPT.
        generate_sft: Whether to generate SFT explanation pairs.

    Returns:
        (dapt_count, sft_count) — records written to each file.
    """
    if provider not in _PROVIDER_CONFIGS:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {list(_PROVIDER_CONFIGS)}")

    cfg = _PROVIDER_CONFIGS[provider]
    client = OpenAI(
        api_key=api_key,
        base_url=cfg["base_url"],  # None = default OpenAI endpoint
    )
    ocr_model         = cfg["ocr_model"]
    structured_model  = cfg["structured_model"]
    explanation_model = cfg["explanation_model"]

    explainer_prompt = system_prompt if system_prompt is not None else EXPLAINER_SYSTEM_PROMPT
    dapt_output.parent.mkdir(parents=True, exist_ok=True)
    sft_output.parent.mkdir(parents=True, exist_ok=True)

    dapt_count = 0
    sft_count = 0

    for i in range(count):
        profile = _build_profile()
        print(
            f"  [{i + 1:>3}/{count}] {profile['panel'][:40]:<40} | {profile['condition'][:35]}"
        )

        try:
            # Step 1: Generate OCR text → DAPT record (pipeline unchanged)
            ocr_text = _generate_ocr_text(client, profile, ocr_model)
            if not ocr_text:
                print("    OCR text generation failed — skipping")
                time.sleep(5)
                continue

            append_jsonl(dapt_output, [{
                "text": ocr_text,
                "source": "synthetic_report",
                "profile": profile,
            }])
            dapt_count += 1

            # Step 2: Generate SFT pair in explainer format
            if generate_sft:
                time.sleep(2)

                # 2a. Simulate deterministic pipeline output for this scenario
                structured_input = _generate_structured_input(client, profile, structured_model)
                if not structured_input:
                    print("    Structured input generation failed — skipping SFT pair")
                    time.sleep(5)
                    continue

                time.sleep(2)

                # 2b. Generate explanation JSON from the structured input
                explanation_str = _generate_explanation_json(
                    client, structured_input, explainer_prompt, explanation_model
                )
                if not explanation_str:
                    print("    Explanation generation failed — skipping SFT pair")
                    time.sleep(5)
                    continue

                try:
                    explanation = json.loads(explanation_str)
                    required_keys = {"disclaimer", "abnormal_values", "normal_values", "medicines"}
                    if not required_keys.issubset(explanation.keys()):
                        print("    Explanation JSON missing required keys — skipping SFT pair")
                    else:
                        user_content = (
                            "Explain these pre-validated lab results to an Indian patient "
                            "in simple language.\n\n"
                            "Pre-validated results:\n"
                            f"{json.dumps(structured_input, ensure_ascii=False, indent=2)}\n\n"
                            "Generate the full explanation JSON. Use the provided values, units, "
                            "ref ranges, and severity classifications EXACTLY — do not re-derive "
                            "or modify them.\n"
                            "Return ONLY JSON."
                        )
                        append_jsonl(sft_output, [{
                            "conversations": [
                                {"role": "system", "content": explainer_prompt},
                                {"role": "user",   "content": user_content},
                                {"role": "assistant", "content": json.dumps(explanation, ensure_ascii=False)},
                            ],
                            "source": "synthetic_sft",
                            "profile": profile,
                            "sft_format": "explainer_v2",
                        }])
                        sft_count += 1
                except json.JSONDecodeError:
                    print("    Explanation JSON parse error — skipping SFT pair")

        except DailyQuotaError:
            remaining = count - (i + 1)
            print()
            print("=" * 65)
            print("  DAILY QUOTA EXHAUSTED — Groq free tier resets at midnight UTC.")
            print(f"  Progress  : {i + 1}/{count} items attempted")
            print(f"  DAPT saved: {dapt_count} records → {dapt_output.name}")
            print(f"  SFT saved : {sft_count} pairs   → {sft_output.name}")
            print()
            print(f"  Resume tomorrow with (appends to existing files):")
            print(f"    python training/collect_all.py --synthetic --count {remaining} --groq-key YOUR_KEY")
            print("=" * 65)
            break

        # 4s gap keeps sustained call rate well within per-minute limits
        time.sleep(4)

    return dapt_count, sft_count
