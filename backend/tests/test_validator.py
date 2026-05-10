"""
Tests for medical_validator.validate().

Focus: the exact root-cause bugs identified in the medical reliability audit.
  - HbA1c = 46.7 % must be REJECTED (hard limit 2–20)
  - Potassium = 22 mEq/L must be REJECTED (hard limit 1.5–9)
  - Potassium with unit "mg/dL" must be FLAGGED (wrong unit class)
  - Good HbA1c value passes and gets correct confidence
  - Consistency check flags mismatched HbA1c + glucose pair
"""

import pytest
from dataclasses import dataclass

from app.models.extraction import ExtractedValue, ExtractionResult
from app.services.medical_validator import (
    validate,
    HARD_LIMITS,
    ALLOWED_UNIT_CLASSES,
    _unit_in_allowed,
    _normalize_for_comparison,
    _compute_confidence,
)



def make_value(
    test_id:       str,
    value_numeric: float,
    unit:          str  = "",
    extraction_tier: str = "digital_text",
    source_page:   int  = 1,
    source_line:   str  = "",
) -> ExtractedValue:
    return ExtractedValue(
        test_id=test_id,
        raw_name=test_id,
        raw_value=str(value_numeric),
        value_numeric=value_numeric,
        unit=unit,
        ref_range_raw="",
        ref_min=None,
        ref_max=None,
        source_page=source_page,
        source_line=source_line,
        extraction_tier=extraction_tier,
    )


def make_result(*values: ExtractedValue) -> ExtractionResult:
    return ExtractionResult(values=list(values))



class TestHbA1cHardLimit:
    def test_hba1c_46_7_rejected(self):
        """The OCR formula constant 46.7 must be rejected as physiologically impossible."""
        ev = make_value("hba1c", 46.7, unit="%")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "rejected"
        assert result.values[0].confidence == 0.0

    def test_hba1c_normal_passes(self):
        ev = make_value("hba1c", 5.9, unit="%")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "passed"
        assert result.values[0].confidence > 0.0

    def test_hba1c_diabetic_range_passes(self):
        ev = make_value("hba1c", 8.2, unit="%")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "passed"

    def test_hba1c_below_minimum_rejected(self):
        ev = make_value("hba1c", 0.5, unit="%")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "rejected"

    def test_hba1c_exactly_at_limit_passes(self):
        ev = make_value("hba1c", 20.0, unit="%")
        result = validate(make_result(ev))
        # 20.0 is the boundary — should still pass (limit is inclusive)
        assert result.values[0].validator_status in ("passed", "flagged")



class TestPotassiumHardLimit:
    def test_potassium_22_rejected(self):
        """K = 22 mEq/L means death — must be rejected as OCR artifact."""
        ev = make_value("potassium", 22.0, unit="mEq/L")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "rejected"
        assert result.values[0].confidence == 0.0
        assert "physiological hard limit" in result.values[0].validator_note.lower()

    def test_potassium_normal_passes(self):
        ev = make_value("potassium", 4.2, unit="mEq/L")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "passed"

    def test_potassium_hyperkalemia_passes(self):
        """6.5 mEq/L is critically elevated but physiologically possible."""
        ev = make_value("potassium", 6.5, unit="mEq/L")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "passed"

    def test_potassium_below_minimum_rejected(self):
        ev = make_value("potassium", 0.5, unit="mEq/L")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "rejected"



class TestUnitCoherence:
    def test_potassium_wrong_unit_flagged(self):
        """Potassium reported in mg/dL is a unit class mismatch — must be flagged."""
        ev = make_value("potassium", 4.2, unit="mg/dL")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "flagged"
        assert result.values[0].confidence < 0.9

    def test_potassium_correct_unit_meq_passes(self):
        ev = make_value("potassium", 4.2, unit="mEq/L")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "passed"

    def test_potassium_correct_unit_mmol_passes(self):
        ev = make_value("potassium", 4.2, unit="mmol/L")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "passed"

    def test_hba1c_mmol_mol_unit_allowed(self):
        """mmol/mol is the IFCC unit for HbA1c — must not be flagged for unit mismatch."""
        ev = make_value("hba1c", 42.0, unit="mmol/mol")
        result = validate(make_result(ev))
        # 42 mmol/mol < hard limit (20% is ~142 mmol/mol) → should pass
        assert result.values[0].validator_status == "passed"

    def test_hemoglobin_cells_per_mcl_unit_flagged(self):
        """Hemoglobin in cells/mcL is an impossible unit class for this test."""
        ev = make_value("hemoglobin", 14.5, unit="cells/mcL")
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "flagged"



class TestNoneValue:
    def test_none_value_rejected(self):
        ev = make_value("hba1c", 5.9, unit="%")
        ev.value_numeric = None  # simulate parse failure
        result = validate(make_result(ev))
        assert result.values[0].validator_status == "rejected"
        assert result.values[0].confidence == 0.0



class TestConfidenceScoring:
    def test_digital_text_unflagged_is_1_0(self):
        assert _compute_confidence("digital_text", flagged=False) == 1.0

    def test_digital_text_flagged_is_0_5(self):
        assert _compute_confidence("digital_text", flagged=True) == 0.5

    def test_vlm_unflagged_is_0_75(self):
        assert _compute_confidence("vlm", flagged=False) == 0.75

    def test_passed_value_has_confidence_1_0(self):
        ev = make_value("hemoglobin", 14.0, unit="g/dL", extraction_tier="digital_text")
        result = validate(make_result(ev))
        assert result.values[0].confidence == 1.0

    def test_flagged_value_has_reduced_confidence(self):
        ev = make_value("potassium", 4.2, unit="mg/dL", extraction_tier="digital_text")
        result = validate(make_result(ev))
        assert result.values[0].confidence == 0.5



class TestConsistencyCheck:
    def test_normal_hba1c_high_fasting_glucose_flags_hba1c(self):
        """HbA1c normal (5.4%) + fasting glucose 145 mg/dL (diabetic) is inconsistent."""
        hba1c   = make_value("hba1c", 5.4, unit="%")
        glucose = make_value("fasting_glucose", 145.0, unit="mg/dL")
        result  = validate(make_result(hba1c, glucose))

        # Find hba1c entry — it should be flagged by consistency check
        hba1c_result = next(v for v in result.values if v.test_id == "hba1c")
        assert hba1c_result.validator_status == "flagged"
        assert "inconsistent" in hba1c_result.validator_note.lower()

    def test_consistent_pair_not_flagged_by_consistency(self):
        """Both normal — no consistency issue."""
        hba1c   = make_value("hba1c", 5.4, unit="%")
        glucose = make_value("fasting_glucose", 90.0, unit="mg/dL")
        result  = validate(make_result(hba1c, glucose))

        hba1c_result = next(v for v in result.values if v.test_id == "hba1c")
        # Should not be flagged for consistency (may still pass or be flagged on unit)
        assert "inconsistent" not in hba1c_result.validator_note.lower()

    def test_differential_count_mismatch_flags_lymphocytes(self):
        """
        Neutrophils 90% + Lymphocytes 75% = 165% is impossible.
        The lymphocyte entry should be flagged for column misalignment.
        """
        neut = make_value("neutrophils",  90.0, unit="%")
        lymp = make_value("lymphocytes",  75.0, unit="%")
        result = validate(make_result(neut, lymp))

        lymp_result = next(v for v in result.values if v.test_id == "lymphocytes")
        assert lymp_result.validator_status == "flagged"
        assert "column" in lymp_result.validator_note.lower() or "sum" in lymp_result.validator_note.lower()



class TestUnitInAllowed:
    def test_meq_l_matches(self):
        assert _unit_in_allowed("mEq/L", {"meq/l", "mmol/l"})

    def test_mmol_l_matches(self):
        assert _unit_in_allowed("mmol/L", {"meq/l", "mmol/l"})

    def test_mg_dl_does_not_match_electrolyte_set(self):
        assert not _unit_in_allowed("mg/dL", {"meq/l", "mmol/l"})

    def test_greek_mu_normalised(self):
        # μIU/mL and uIU/mL should be equivalent
        assert _unit_in_allowed("μIU/mL", {"uiu/ml", "miu/ml"})

    def test_percent_matches_hba1c_set(self):
        assert _unit_in_allowed("%", {"%", "percent", "mmol/mol"})



class TestHardLimitsCompleteness:
    def test_key_tests_have_limits(self):
        must_have = [
            "hba1c", "potassium", "sodium", "hemoglobin",
            "creatinine", "tsh", "ldl", "fasting_glucose",
        ]
        for key in must_have:
            assert key in HARD_LIMITS, f"Missing hard limit for {key}"

    def test_all_limits_are_valid_ranges(self):
        for test_id, (lo, hi) in HARD_LIMITS.items():
            assert lo < hi, f"Invalid hard limit for {test_id}: {lo} >= {hi}"
            assert lo >= 0 or test_id in {"egfr"}, \
                f"Unexpected negative lower limit for {test_id}"
