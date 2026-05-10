"""
Tests for ontology.normalize().

Focus: unit conversions that fix input/reporting-format differences.
  - HbA1c IFCC (mmol/mol) → NGSP (%)
  - Glucose mmol/L → mg/dL
  - Creatinine μmol/L → mg/dL
  - Rejected values are left untouched
  - Catalog range back-fill for values without report reference ranges
"""

import pytest

from app.models.extraction import ExtractedValue, ExtractionResult
from app.services.ontology import normalize, _apply_unit_conversion, _apply_catalog_ranges, _key
from app.services.medical_validator import validate



def make_ev(
    test_id:        str,
    value_numeric:  float,
    unit:           str,
    validator_status: str = "passed",
    ref_min=None,
    ref_max=None,
) -> ExtractedValue:
    ev = ExtractedValue(
        test_id=test_id,
        raw_name=test_id,
        raw_value=str(value_numeric),
        value_numeric=value_numeric,
        unit=unit,
        ref_range_raw="",
        ref_min=ref_min,
        ref_max=ref_max,
        source_page=1,
        source_line="test line",
        extraction_tier="digital_text",
    )
    ev.validator_status = validator_status
    return ev


def make_result(*values: ExtractedValue) -> ExtractionResult:
    return ExtractionResult(values=list(values))



class TestHbA1cConversion:
    def test_ifcc_42_converts_to_ngsp_6_0(self):
        """42 mmol/mol is a common IFCC HbA1c — should convert to ~6.0% NGSP."""
        ev = make_ev("hba1c", 42.0, "mmol/mol")
        normalize(make_result(ev))
        assert ev.unit != "mmol/mol"  # unit changed
        assert abs(ev.value_numeric - 6.0) < 0.2  # ~6.0% (NGSP formula: 42/10.929+2.15)
        assert "converted" in ev.validator_note.lower()

    def test_ifcc_53_converts_to_ngsp_7_0(self):
        """53 mmol/mol corresponds to 7.0% NGSP (diabetic threshold)."""
        ev = make_ev("hba1c", 53.0, "mmol/mol")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 7.0) < 0.2

    def test_ngsp_percent_not_converted(self):
        """% values should not be converted — they are already in canonical form."""
        ev = make_ev("hba1c", 5.9, "%")
        original_value = ev.value_numeric
        normalize(make_result(ev))
        assert ev.value_numeric == original_value
        assert ev.unit == "%"

    def test_conversion_note_appended(self):
        ev = make_ev("hba1c", 42.0, "mmol/mol")
        normalize(make_result(ev))
        assert ev.validator_note  # should not be empty



class TestGlucoseConversion:
    def test_glucose_5_mmol_l_converts_to_90_mg_dl(self):
        """5 mmol/L × 18.016 = 90.1 mg/dL (normal fasting)."""
        ev = make_ev("fasting_glucose", 5.0, "mmol/l")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 90.1) < 0.5

    def test_glucose_7_mmol_l_converts_to_diabetic_range(self):
        """7 mmol/L × 18.016 = 126.1 mg/dL (diabetic fasting threshold)."""
        ev = make_ev("fasting_glucose", 7.0, "mmol/l")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 126.1) < 1.0

    def test_glucose_mg_dl_not_converted(self):
        ev = make_ev("fasting_glucose", 95.0, "mg/dL")
        normalize(make_result(ev))
        assert ev.value_numeric == 95.0
        assert ev.unit == "mg/dL"

    def test_pp_glucose_converted(self):
        ev = make_ev("pp_glucose", 9.0, "mmol/l")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 162.1) < 1.0



class TestCreatinineConversion:
    def test_creatinine_88_umol_converts_to_1_mg_dl(self):
        """88.4 μmol/L / 88.4 = 1.0 mg/dL (normal upper bound for creatinine)."""
        ev = make_ev("creatinine", 88.4, "umol/l")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 1.0) < 0.05

    def test_creatinine_mg_dl_unchanged(self):
        ev = make_ev("creatinine", 1.1, "mg/dL")
        normalize(make_result(ev))
        assert ev.value_numeric == 1.1



class TestLipidConversions:
    def test_total_cholesterol_5_2_mmol_converts_to_201_mg_dl(self):
        """5.2 mmol/L × 38.67 = 201.1 mg/dL."""
        ev = make_ev("total_cholesterol", 5.2, "mmol/l")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 201.1) < 1.5

    def test_triglycerides_1_7_mmol_converts(self):
        """1.7 mmol/L × 88.57 = 150.6 mg/dL."""
        ev = make_ev("triglycerides", 1.7, "mmol/l")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 150.6) < 2.0



class TestVitaminDConversion:
    def test_vitamin_d_nmol_converts_to_ng_ml(self):
        """50 nmol/L / 2.496 = 20.0 ng/mL (approximate)."""
        ev = make_ev("vitamin_d", 50.0, "nmol/l")
        normalize(make_result(ev))
        assert abs(ev.value_numeric - 20.0) < 0.5



class TestRejectedNotConverted:
    def test_rejected_value_is_not_converted(self):
        """Rejected values (e.g. HbA1c=46.7) must not be unit-converted."""
        ev = make_ev("hba1c", 46.7, "mmol/mol", validator_status="rejected")
        original_value = ev.value_numeric
        normalize(make_result(ev))
        assert ev.value_numeric == original_value  # untouched
        assert "converted" not in ev.validator_note.lower()

    def test_rejected_value_unit_unchanged(self):
        ev = make_ev("fasting_glucose", 46.7, "mmol/l", validator_status="rejected")
        ev.unit = "mmol/l"
        normalize(make_result(ev))
        assert ev.unit == "mmol/l"



class TestCatalogRangeBackfill:
    def test_missing_ranges_filled_from_catalog(self):
        """When the report has no reference range, catalog values should be filled in."""
        ev = make_ev("hemoglobin", 14.0, "g/dL", ref_min=None, ref_max=None)
        normalize(make_result(ev))
        # hemoglobin should have catalog reference ranges
        # Exact values depend on tests.json — just check they are now set
        assert ev.ref_min is not None or ev.ref_max is not None

    def test_existing_ranges_not_overwritten(self):
        """Report-specific ranges (from the actual lab report) must be preserved."""
        ev = make_ev("hemoglobin", 14.0, "g/dL", ref_min=12.5, ref_max=16.5)
        normalize(make_result(ev))
        assert ev.ref_min == 12.5
        assert ev.ref_max == 16.5



class TestKeyHelper:
    def test_lowercase(self):
        assert _key("mmol/L") == "mmol/l"

    def test_greek_mu_to_u(self):
        assert _key("μmol/L") == "umol/l"

    def test_micro_to_u(self):
        assert _key("µg/dL") == "ug/dl"

    def test_spaces_removed(self):
        assert _key("mmol / L") == "mmol/l"



class TestValidateThenNormalize:
    def test_valid_ifcc_hba1c_passes_and_converts(self):
        """End-to-end: a valid IFCC HbA1c value should pass validation and be converted."""
        ev = make_ev("hba1c", 42.0, "mmol/mol")
        result = make_result(ev)
        validate(result)   # sets validator_status
        normalize(result)  # converts mmol/mol → %

        assert ev.validator_status == "passed"
        assert abs(ev.value_numeric - 6.0) < 0.3

    def test_invalid_hba1c_rejected_not_converted(self):
        """An invalid value (e.g. 46.7 %) should be rejected and NOT converted."""
        ev = make_ev("hba1c", 46.7, "%")
        result = make_result(ev)
        validate(result)
        normalize(result)

        assert ev.validator_status == "rejected"
        # No "converted" note should appear on a rejected value
        assert "converted" not in ev.validator_note.lower()
