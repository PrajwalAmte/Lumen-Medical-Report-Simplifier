"""
Ontology Normalizer — canonical unit conversions and catalog range back-fill.

Runs AFTER medical_validator.validate().  Rejected values are left untouched.

Two responsibilities:
  1. Unit conversion — transforms region-specific or SI units to the canonical
     unit used in tests.json so that range comparison is apples-to-apples.
     e.g. IFCC HbA1c mmol/mol → NGSP %, glucose mmol/L → mg/dL.

  2. Catalog range back-fill — if the report did not contain a reference range
     for a test, look it up from tests.json so the LLM has a concrete threshold.

Unit conversions are deterministic, closed-form arithmetic — no LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from app.models.extraction import ExtractedValue, ExtractionResult



_CATALOG_PATH = Path(__file__).parent.parent / "catalog" / "tests.json"

def _load_catalog() -> dict:
    try:
        with open(_CATALOG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

_CATALOG: dict = _load_catalog()


#
# Structure: { test_id: { source_unit_lowercase: conversion_lambda } }
# The lambda receives the numeric value in the source unit and returns the
# value in the canonical unit (matching tests.json).

_CONVERSIONS: dict[str, dict[str, Callable[[float], float]]] = {
    # HbA1c: IFCC (mmol/mol) → NGSP (%)
    # Equation: NGSP % = (IFCC / 10.929) + 2.15  (IFCC–NGSP Master Equation)
    "hba1c": {
        "mmol/mol": lambda v: round((v / 10.929) + 2.15, 1),
    },

    # Glucose: mmol/L → mg/dL (multiply by molecular weight factor 18.016)
    "fasting_glucose":  {"mmol/l": lambda v: round(v * 18.016, 1)},
    "pp_glucose":       {"mmol/l": lambda v: round(v * 18.016, 1)},
    "random_glucose":   {"mmol/l": lambda v: round(v * 18.016, 1)},

    # Creatinine: μmol/L → mg/dL
    "creatinine": {
        "umol/l":  lambda v: round(v / 88.4, 2),
        "μmol/l":  lambda v: round(v / 88.4, 2),
        "µmol/l":  lambda v: round(v / 88.4, 2),
        "mmol/l":  lambda v: round(v * 11.312, 2),
    },

    # Uric acid: μmol/L → mg/dL
    "uric_acid": {
        "umol/l": lambda v: round(v / 59.485, 1),
        "μmol/l": lambda v: round(v / 59.485, 1),
    },

    # Calcium: mmol/L → mg/dL
    "calcium": {
        "mmol/l": lambda v: round(v * 4.008, 1),
    },

    # Lipids: mmol/L → mg/dL
    "total_cholesterol": {"mmol/l": lambda v: round(v * 38.67, 1)},
    "ldl":               {"mmol/l": lambda v: round(v * 38.67, 1)},
    "hdl":               {"mmol/l": lambda v: round(v * 38.67, 1)},
    "triglycerides":     {"mmol/l": lambda v: round(v * 88.57, 1)},
    "vldl":              {"mmol/l": lambda v: round(v * 88.57, 1)},

    # Hemoglobin: g/L → g/dL
    "hemoglobin": {
        "g/l": lambda v: round(v / 10.0, 1),
    },

    # Vitamin D: nmol/L → ng/mL
    "vitamin_d": {
        "nmol/l": lambda v: round(v / 2.496, 1),
    },

    # Vitamin B12: pmol/L → pg/mL
    "vitamin_b12": {
        "pmol/l": lambda v: round(v * 1.3554, 1),
    },
}



def _key(unit: str) -> str:
    """Lowercase unit key for conversion lookup, strip Greek chars → ASCII."""
    u = unit.lower().strip()
    u = u.replace("μ", "u").replace("µ", "u").replace(" ", "")
    return u


def _apply_unit_conversion(v: ExtractedValue) -> None:
    """Mutate v in-place: convert value_numeric and unit to canonical form."""
    conversions_for_test = _CONVERSIONS.get(v.test_id)
    if not conversions_for_test or v.value_numeric is None:
        return

    fn = conversions_for_test.get(_key(v.unit))
    if fn is None:
        return

    original_unit   = v.unit
    original_value  = v.value_numeric
    v.value_numeric = fn(original_value)

    # Determine canonical unit by checking what the catalog specifies
    catalog_entry = _CATALOG.get(v.test_id, {})
    canonical_unit = catalog_entry.get("unit", "")
    if canonical_unit:
        v.unit = canonical_unit
    # If catalog doesn't list one, leave v.unit as-is (caller decides)

    # Append conversion lineage to validator_note for traceability
    note = (
        f"Unit converted: {original_value} {original_unit} "
        f"→ {v.value_numeric} {v.unit}"
    )
    v.validator_note = (v.validator_note + "; " if v.validator_note else "") + note


def _apply_catalog_ranges(v: ExtractedValue) -> None:
    """Fill ref_min / ref_max from the catalog if the report did not supply them."""
    if v.ref_min is not None and v.ref_max is not None:
        return  # report-specific range available, trust it

    entry = _CATALOG.get(v.test_id, {})
    if not entry:
        return

    if v.ref_min is None:
        normal_min = entry.get("normal_min")
        if normal_min is not None:
            v.ref_min = float(normal_min)

    if v.ref_max is None:
        normal_max = entry.get("normal_max")
        if normal_max is not None:
            v.ref_max = float(normal_max)



def normalize(result: ExtractionResult) -> ExtractionResult:
    """
    Apply unit conversions and catalog range back-fill to all non-rejected values.

    Returns the same ExtractionResult with mutations applied in place.
    """
    for v in result.values:
        if v.validator_status == "rejected":
            continue
        _apply_unit_conversion(v)
        _apply_catalog_ranges(v)

    return result
