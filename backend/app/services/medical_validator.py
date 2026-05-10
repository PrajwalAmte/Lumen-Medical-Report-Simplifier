"""
Medical Validator — deterministic safety gate between extraction and the LLM.

Every extracted value passes through here before reaching the explanation layer.
The validator never calls external APIs; it is pure Python rules derived from
established clinical reference ranges.

Three check levels (applied in order, strictest first):
  1. Hard physiological limits  — values outside are OCR/extraction artifacts
  2. Unit coherence             — unit class must match the test
  3. Inter-test consistency     — cross-value logic catches paired anomalies

Status outcomes:
  "passed"   — value is clinically plausible, proceed to LLM
  "flagged"  — value is suspect (wrong unit, consistency issue); LLM receives it
               with a low confidence score and a note to verify with doctor
  "rejected" — value is physiologically impossible; NOT sent to LLM at all;
               stored separately as extraction_artifact for transparency
"""

from typing import Dict, List, Set, Tuple

from app.models.extraction import ExtractedValue, ExtractionResult
from app.services.catalog import TEST_CATALOG


#
# tests.json is the single source of truth.  Add or edit an entry there;
# nothing here needs to change.
#
# Catalog fields consumed:
#   hard_limit_min / hard_limit_max      — physiological impossibility bounds
#   hard_limit_variants                  — {unit_string: [min, max]} overrides
#                                          for tests with multiple numeric scales
#                                          (e.g. HbA1c mmol/mol vs %)
#   allowed_unit_classes                 — acceptable input unit strings

def _build_hard_limits() -> Dict[str, Tuple[float, float]]:
    return {
        test_id: (meta["hard_limit_min"], meta["hard_limit_max"])
        for test_id, meta in TEST_CATALOG.items()
        if "hard_limit_min" in meta and "hard_limit_max" in meta
    }


def _build_hard_limit_variants() -> Dict[str, Dict[str, Tuple[float, float]]]:
    """Per-unit overrides for tests that have multiple valid numeric scales."""
    out: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for test_id, meta in TEST_CATALOG.items():
        variants = meta.get("hard_limit_variants")
        if variants:
            out[test_id] = {unit: tuple(bounds) for unit, bounds in variants.items()}
    return out


def _build_allowed_units() -> Dict[str, Set[str]]:
    return {
        test_id: set(meta["allowed_unit_classes"])
        for test_id, meta in TEST_CATALOG.items()
        if "allowed_unit_classes" in meta
    }


HARD_LIMITS: Dict[str, Tuple[float, float]] = _build_hard_limits()
HARD_LIMIT_VARIANTS: Dict[str, Dict[str, Tuple[float, float]]] = _build_hard_limit_variants()
ALLOWED_UNIT_CLASSES: Dict[str, Set[str]] = _build_allowed_units()


#
# Old code that imported HARD_LIMITS or ALLOWED_UNIT_CLASSES directly still works;
# those names now point to catalog-derived dicts rather than hard-coded literals.




def _normalize_for_comparison(unit: str) -> str:
    """Collapse unit to a canonical lowercase ASCII form for set comparison."""
    u = unit.lower().strip()
    # Greek mu and variants → u
    u = u.replace("μ", "u").replace("µ", "u")
    # Remove whitespace
    u = u.replace(" ", "")
    return u


def _unit_in_allowed(unit: str, allowed: Set[str]) -> bool:
    """Case-/unicode-insensitive membership check against an allowed set."""
    u = _normalize_for_comparison(unit)
    return any(_normalize_for_comparison(a) == u for a in allowed)


def _compute_confidence(tier: str, flagged: bool = False) -> float:
    tier_weights = {
        "digital_text": 1.0,
        "paddle_table": 0.9,
        "vlm":          0.75,
    }
    base = tier_weights.get(tier, 0.7)
    if flagged:
        base *= 0.5
    return round(min(base, 1.0), 2)



def _check_consistency(values: List[ExtractedValue]) -> List[Tuple[str, str]]:
    """
    Cross-value logic.  Returns (test_id, note) pairs for values that should
    be flagged due to paired inconsistency.  Only considers "passed" values
    so a single bad extraction doesn't cascade.
    """
    warnings: list[tuple[str, str]] = []
    passed = {
        v.test_id: v
        for v in values
        if v.validator_status == "passed" and v.value_numeric is not None
    }

    # HbA1c vs fasting glucose — ADA clinical definitions
    hba1c   = passed.get("hba1c")
    fasting = passed.get("fasting_glucose")
    if hba1c and fasting:
        if hba1c.value_numeric <= 5.6 and fasting.value_numeric >= 126:
            warnings.append((
                "hba1c",
                "HbA1c is normal but fasting glucose is in the diabetic range "
                "— values are clinically inconsistent, verify extraction"
            ))
        if hba1c.value_numeric >= 6.5 and fasting.value_numeric < 70:
            warnings.append((
                "fasting_glucose",
                "HbA1c is in the diabetic range but fasting glucose is below normal "
                "— values are clinically inconsistent, verify extraction"
            ))

    # Neutrophil% + Lymphocyte% together should be between 50–115%
    # (remaining differential: monocytes, eosinophils, basophils ≈ 5–15%)
    neut = passed.get("neutrophils")
    lymp = passed.get("lymphocytes")
    if neut and lymp:
        total = neut.value_numeric + lymp.value_numeric
        if total > 115 or total < 40:
            warnings.append((
                "lymphocytes",
                f"Neutrophils ({neut.value_numeric:.0f}%) + Lymphocytes "
                f"({lymp.value_numeric:.0f}%) sum to {total:.0f}% — expected "
                f"~60–95%, possible table column misalignment"
            ))

    return warnings



def validate(result: ExtractionResult) -> ExtractionResult:
    """
    Validate all ExtractedValues in place.  Returns the same ExtractionResult
    with validator_status, validator_note, and confidence set on every value.

    Call order: hard limits → unit coherence → inter-test consistency.
    """

    for v in result.values:
        # Un-parseable numeric — reject immediately
        if v.value_numeric is None:
            v.validator_status = "rejected"
            v.validator_note   = "Could not parse a numeric value from the extracted text"
            v.confidence       = 0.0
            continue

        notes: list[str] = []
        reject = False
        flag   = False

        limits = HARD_LIMITS.get(v.test_id)
        if limits:
            # Check for a unit-specific override first (e.g. HbA1c mmol/mol vs %)
            variants = HARD_LIMIT_VARIANTS.get(v.test_id)
            if variants and v.unit:
                u_norm = _normalize_for_comparison(v.unit)
                for variant_unit, variant_bounds in variants.items():
                    if _normalize_for_comparison(variant_unit) == u_norm:
                        limits = variant_bounds
                        break

            hard_min, hard_max = limits
            if v.value_numeric < hard_min or v.value_numeric > hard_max:
                reject = True
                notes.append(
                    f"Value {v.value_numeric} {v.unit} is outside the physiological "
                    f"hard limit [{hard_min}–{hard_max}] — almost certainly an OCR "
                    f"artifact (e.g. extracted from a formula or footnote)"
                )

        if not reject:
            allowed = ALLOWED_UNIT_CLASSES.get(v.test_id)
            if allowed and v.unit:
                if not _unit_in_allowed(v.unit, allowed):
                    flag = True
                    notes.append(
                        f"Unit '{v.unit}' is not a recognised unit class for "
                        f"{v.test_id} (expected one of: "
                        + ", ".join(sorted(allowed)) + ")"
                    )

        if reject:
            v.validator_status = "rejected"
            v.confidence       = 0.0
        elif flag:
            v.validator_status = "flagged"
            v.confidence       = _compute_confidence(v.extraction_tier, flagged=True)
        else:
            v.validator_status = "passed"
            v.confidence       = _compute_confidence(v.extraction_tier)

        v.validator_note = "; ".join(notes)

    for test_id, note in _check_consistency(result.values):
        for v in result.values:
            if v.test_id == test_id and v.validator_status == "passed":
                v.validator_status = "flagged"
                v.validator_note   = (
                    (v.validator_note + "; " if v.validator_note else "") + note
                )
                v.confidence = _compute_confidence(v.extraction_tier, flagged=True)

    return result
