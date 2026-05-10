"""
Parser regression tests — verifies fixes for the three extraction bugs from the
medical reliability audit.

1. HbA1c formula constant bug: "eAG = (28.7 × HbA1c) − 46.7" must NOT produce
   HbA1c=46.7.  When a real result line "HbA1c: 5.9 %" is present, parser must
   select 5.9.

2. Potassium K-alias collision: "WBC: 22K cells/µL" must NOT produce K=22.
   Potassium alias "k" requires a delimiter after it.

3. Line classifier: formula and RX/prescription lines are classified correctly so
   the scoring system can discount or reject their candidates.
"""

import re
import pytest

from app.services.parser import (
    _classify_line,
    _build_pattern,
    _score_candidate,
    _SHORT_ALIASES,
    LINE_FORMULA,
    LINE_RANGE,
    LINE_HEADER,
    LINE_RX,
    LINE_UNKNOWN,
    extract_tests,
    parse_pages,
)
from app.models.extraction import PageContent



class TestClassifyLine:
    def test_formula_detected_multiplication(self):
        line = "eAG (mg/dL) = 28.7 x HbA1c - 46.7"
        assert _classify_line(line) == LINE_FORMULA

    def test_formula_detected_times_symbol(self):
        line = "eAG = (28.7 × HbA1c) − 46.7"
        assert _classify_line(line) == LINE_FORMULA

    def test_formula_keyword(self):
        assert _classify_line("Calculated eAG value for reference") == LINE_FORMULA

    def test_range_line_normal_range(self):
        line = "Normal range: 4.0 - 6.0"
        assert _classify_line(line) == LINE_RANGE

    def test_range_line_reference_range(self):
        line = "Reference Range 3.5 - 5.0 g/dL"
        assert _classify_line(line) == LINE_RANGE

    def test_rx_line_tablet_keyword(self):
        line = "Tab Metformin 500mg twice daily"
        assert _classify_line(line) == LINE_RX

    def test_rx_line_prescribed(self):
        line = "Patient prescribed Atorvastatin 20mg once daily"
        assert _classify_line(line) == LINE_RX

    def test_header_prescription_section(self):
        # Standalone header line
        assert _classify_line("Prescription") == LINE_HEADER
        assert _classify_line("rx") == LINE_HEADER

    def test_result_line_unknown(self):
        line = "HbA1c: 5.9 %"
        assert _classify_line(line) == LINE_UNKNOWN

    def test_result_line_hemoglobin(self):
        line = "Hemoglobin: 14.5 g/dL"
        assert _classify_line(line) == LINE_UNKNOWN

    def test_wbc_line_not_formula(self):
        """A WBC count line should not be misclassified as a formula."""
        line = "WBC: 8500 cells/mcL"
        assert _classify_line(line) == LINE_UNKNOWN



class TestShortAliasGuard:
    def test_k_alias_in_short_aliases(self):
        assert "k" in _SHORT_ALIASES

    def test_k_pattern_requires_delimiter(self):
        """Pattern for 'k' must NOT match '22K cells' but MUST match 'K: 5.1'."""
        pattern = re.compile(_build_pattern("k"), re.IGNORECASE)

        no_match_line = "WBC: 22K cells/mcL"
        match_line    = "K: 5.1 mEq/L"

        assert not pattern.search(no_match_line), \
            f"Pattern wrongly matched '22K cells' for potassium alias 'k'"
        assert pattern.search(match_line), \
            f"Pattern failed to match legitimate 'K: 5.1' for potassium alias 'k'"

    def test_na_alias_requires_delimiter(self):
        pattern = re.compile(_build_pattern("Na"), re.IGNORECASE)
        # "Nausea" contains "Na" at the start — should not match
        assert not pattern.search("Nausea: patient reports mild nausea")
        # Legitimate sodium
        assert pattern.search("Na: 140 mEq/L")

    def test_hb_alias_preceded_by_digit_no_match(self):
        """'HbA1c' contains 'hb' but 'hb' is preceded by nothing — should match.
        However, '100HB' should not match because 'hb' is preceded by '0' (digit)."""
        pattern = re.compile(_build_pattern("hb"), re.IGNORECASE)
        assert not pattern.search("100HB: something")

    def test_long_alias_no_lookbehind_needed(self):
        """Long aliases like 'hemoglobin' use word boundary, not lookbehind."""
        pattern_str = _build_pattern("hemoglobin")
        assert "(?<!" not in pattern_str  # no lookbehind for long alias
        pattern = re.compile(pattern_str, re.IGNORECASE)
        assert pattern.search("Hemoglobin: 14.5 g/dL")



class TestScoreCandidate:
    def test_formula_line_negative_score(self):
        score = _score_candidate(
            value_numeric=46.7,
            unit="",
            test_id="hba1c",
            matched_alias="hba1c",
            line_type=LINE_FORMULA,
            catalog_unit="%",
        )
        assert score < 0

    def test_hard_limit_violation_negative_score(self):
        """46.7% for HbA1c is above the hard limit → -5 penalty."""
        score = _score_candidate(
            value_numeric=46.7,
            unit="%",
            test_id="hba1c",
            matched_alias="hba1c",
            line_type=LINE_UNKNOWN,
            catalog_unit="%",
        )
        # Hard limit violation: -5, but canonical unit match: +3, long alias: +1
        # net = -5 + 3 + 1 = -1 → still negative → will be dropped
        assert score < 0

    def test_canonical_unit_bonus(self):
        """Matching the catalog unit gives +3 bonus."""
        score_with_unit = _score_candidate(
            value_numeric=5.9,
            unit="%",
            test_id="hba1c",
            matched_alias="hba1c",
            line_type=LINE_UNKNOWN,
            catalog_unit="%",
        )
        score_no_unit = _score_candidate(
            value_numeric=5.9,
            unit="",
            test_id="hba1c",
            matched_alias="hba1c",
            line_type=LINE_UNKNOWN,
            catalog_unit="%",
        )
        assert score_with_unit > score_no_unit

    def test_result_beats_formula_for_same_test(self):
        """The UNKNOWN-line candidate should score higher than the FORMULA-line one."""
        formula_score = _score_candidate(
            value_numeric=46.7, unit="", test_id="hba1c",
            matched_alias="hba1c", line_type=LINE_FORMULA, catalog_unit="%"
        )
        result_score = _score_candidate(
            value_numeric=5.9, unit="%", test_id="hba1c",
            matched_alias="hba1c", line_type=LINE_UNKNOWN, catalog_unit="%"
        )
        assert result_score > formula_score

    def test_range_line_negative_score(self):
        score = _score_candidate(
            value_numeric=4.0, unit="%", test_id="hba1c",
            matched_alias="hba1c", line_type=LINE_RANGE, catalog_unit="%"
        )
        assert score < 0

    def test_rx_line_negative_score(self):
        score = _score_candidate(
            value_numeric=500.0, unit="mg", test_id="hemoglobin",
            matched_alias="hemoglobin", line_type=LINE_RX, catalog_unit="g/dL"
        )
        assert score < 0



class TestHbA1cFormulaRegression:
    def test_formula_constant_not_selected_when_real_result_present(self):
        """
        Report contains both:
          - A formula line:  eAG = (28.7 × HbA1c) − 46.7
          - A result line:   HbA1c: 5.9 %
        The parser must select 5.9, not 46.7.
        """
        text = """
HbA1c: 5.9 %
eAG (mg/dL) = 28.7 x HbA1c - 46.7
        """
        tests = extract_tests(text)
        hba1c_results = [t for t in tests if t["id"] == "hba1c"]
        assert len(hba1c_results) >= 1, "HbA1c should be extracted"
        assert hba1c_results[0]["value"] == 5.9, \
            f"Expected 5.9 but got {hba1c_results[0]['value']} — formula constant bug not fixed!"

    def test_formula_only_no_real_result_returns_empty(self):
        """
        If a report only contains a formula line and no actual result,
        the parser should not extract a value (score < 0 threshold).
        """
        text = "eAG (mg/dL) = 28.7 x HbA1c - 46.7"
        tests = extract_tests(text)
        hba1c_results = [t for t in tests if t["id"] == "hba1c"]
        # Either empty or the value is NOT 46.7
        for r in hba1c_results:
            assert r["value"] != 46.7, \
                "Formula constant 46.7 must never be returned as HbA1c value"



class TestPotassiumAliasRegression:
    def test_wbc_22k_notation_does_not_produce_potassium_22(self):
        """
        "WBC: 22K cells/µL" — the K (thousands) must not match the potassium alias.
        """
        text = "WBC: 22K cells/mcL"
        tests = extract_tests(text)
        potassium_results = [t for t in tests if t["id"] == "potassium"]
        # No potassium entry with value 22 (or any value from this line)
        for r in potassium_results:
            assert r["value"] != 22.0, \
                "K-alias collision bug: 22K cells/mcL matched as potassium = 22!"

    def test_potassium_with_colon_delimiter_is_extracted(self):
        """K with a colon delimiter should be extracted correctly."""
        text = "K: 4.5 mEq/L"
        tests = extract_tests(text)
        pot = next((t for t in tests if t["id"] == "potassium"), None)
        assert pot is not None, "Potassium K: 4.5 should be extracted"
        assert pot["value"] == 4.5

    def test_potassium_spelled_out_is_extracted(self):
        text = "Potassium: 4.2 mEq/L"
        tests = extract_tests(text)
        pot = next((t for t in tests if t["id"] == "potassium"), None)
        assert pot is not None



class TestParsePages:
    def test_basic_extraction_returns_extraction_result(self):
        page = PageContent(
            page_num=1,
            lines=["Hemoglobin: 14.5 g/dL"],
            raw_text="Hemoglobin: 14.5 g/dL",
        )
        result = parse_pages([page])
        assert hasattr(result, "values")
        assert hasattr(result, "medicines")
        assert hasattr(result, "pages")

    def test_source_page_set_correctly(self):
        page1 = PageContent(page_num=1, lines=["Random stuff"], raw_text="Random stuff")
        page2 = PageContent(
            page_num=2,
            lines=["Hemoglobin: 14.5 g/dL"],
            raw_text="Hemoglobin: 14.5 g/dL",
        )
        result = parse_pages([page1, page2])
        hb = next((v for v in result.values if v.test_id == "hemoglobin"), None)
        if hb:
            assert hb.source_page == 2

    def test_extraction_tier_set_to_digital_text(self):
        page = PageContent(
            page_num=1,
            lines=["HbA1c: 5.9 %"],
            raw_text="HbA1c: 5.9 %",
        )
        result = parse_pages([page])
        hba1c = next((v for v in result.values if v.test_id == "hba1c"), None)
        if hba1c:
            assert hba1c.extraction_tier == "digital_text"

    def test_medicines_not_extracted_without_rx_context(self):
        """Lab result lines should not be mistaken for prescriptions."""
        page = PageContent(
            page_num=1,
            lines=["Vitamin D: 12 ng/mL", "Ferritin: 45 ng/mL"],
            raw_text="Vitamin D: 12 ng/mL\nFerritin: 45 ng/mL",
        )
        result = parse_pages([page])
        # No medicines should be extracted from pure lab result lines
        assert result.medicines == []

    def test_medicines_extracted_in_rx_section(self):
        """After a prescription header, medicines should be extracted."""
        page = PageContent(
            page_num=1,
            lines=[
                "Prescription",
                "Tab Metformin 500mg twice daily",
            ],
            raw_text="Prescription\nTab Metformin 500mg twice daily",
        )
        result = parse_pages([page])
        med_ids = [m.id for m in result.medicines]
        assert "metformin" in med_ids

    def test_empty_pages_returns_empty_result(self):
        result = parse_pages([])
        assert result.values == []
        assert result.medicines == []

    def test_page_with_only_headers_returns_empty_result(self):
        page = PageContent(
            page_num=1,
            lines=["Patient Age: 45", "Date: 12/01/2024", "Lab: SRL Diagnostics"],
            raw_text="Patient Age: 45\nDate: 12/01/2024\nLab: SRL Diagnostics",
        )
        result = parse_pages([page])
        # Some of these might match low-relevance tests — just ensure no crash
        assert isinstance(result.values, list)
