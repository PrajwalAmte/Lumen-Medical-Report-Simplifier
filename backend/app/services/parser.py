"""
Medical text parser — extracts lab test values and medicine names from OCR output.

Primary API (new pipeline):
  parse_pages(pages: List[PageContent]) -> ExtractionResult

Backward-compatible API (preserved for existing callers and tests):
  extract_tests(text: str) -> List[Dict]
  extract_medicines(text: str) -> List[Dict]
  parse_medical_text(text: str) -> Dict
  _normalize_test_name(raw: str) -> Optional[str]
  _normalize_unit(raw: str) -> str
  _safe_float(x) -> Optional[float]
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from app.models.extraction import ExtractedValue, ExtractedMedicine, ExtractionResult, PageContent
from app.services.catalog import TEST_CATALOG, MEDICINE_CATALOG, SYNONYMS, UNITS
from app.services.medical_validator import HARD_LIMITS




def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalize_test_name(raw: str) -> Optional[str]:
    key = raw.lower().strip()
    if key in SYNONYMS:
        return SYNONYMS[key]
    for test_id, meta in TEST_CATALOG.items():
        if key == test_id:
            return test_id
        if key in [a.lower() for a in meta.get("aliases", [])]:
            return test_id
    return None


def _normalize_unit(raw: str) -> str:
    raw = raw.strip().lower()
    return UNITS.get(raw, raw)


def _safe_float(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None



LINE_RESULT  = "RESULT"
LINE_RANGE   = "RANGE"
LINE_FORMULA = "FORMULA"
LINE_HEADER  = "HEADER"
LINE_RX      = "RX"
LINE_UNKNOWN = "UNKNOWN"

_FORMULA_RE = re.compile(
    r"""
    \d\s*[×x\*]\s*\d              # product e.g. 28.7 × HbA1c
    | \(\s*\d[\d.]*\s*[×x\*\+\-]\s*\d  # parenthesised arithmetic
    | \b(?:formula|eag|conversion|calculated|equation|calc\.?)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RANGE_LINE_RE = re.compile(
    r"""
    \b(?:normal\s*(?:range)?
        |ref(?:erence)?\s*(?:range)?
        |expected\s*(?:range)?
        |lower\s*limit
        |upper\s*limit
        |reference\s*interval
    )\s*:?\s*\d
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RX_CONTEXT_RE = re.compile(
    r"""
    \b(?:tablet|tab\.?|cap(?:sule)?|mcg\b|iu\b|units?\b
        |dose|daily|bd|tds|od|sos|qid|tid
        |prescribed|twice|thrice|once
        |before\s+food|after\s+food|with\s+food
        |morning|evening|night|bedtime
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SECTION_HEADER_RE = re.compile(
    r"""^\s*
    (?:prescription|rx\.?|doctor\'?s?\s+(?:order|prescription)
       |medication|medications?|advised|treatment\s+plan
    )\s*:?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def _classify_line(line: str) -> str:
    """
    Classify a single line of report text into a semantic category.

    Priority order: HEADER > FORMULA > RANGE > RX > UNKNOWN.
    UNKNOWN is treated as a potential result line by the scoring system.
    """
    if _SECTION_HEADER_RE.search(line):
        return LINE_HEADER
    if _FORMULA_RE.search(line):
        return LINE_FORMULA
    if _RANGE_LINE_RE.search(line):
        return LINE_RANGE
    if _RX_CONTEXT_RE.search(line):
        return LINE_RX
    return LINE_UNKNOWN



# Short aliases (≤ 2 chars) that could collide with numeric suffixes
# ("22K cells", "5mg tablet").  Derived from catalog at startup — any alias
# with stripped length ≤ 2 requires (?<!\d) lookbehind + hard delimiter.

def _build_short_aliases() -> frozenset:
    shorts: set = set()
    for meta in TEST_CATALOG.values():
        for alias in meta.get("aliases", []):
            stripped = alias.strip()
            if len(stripped) <= 2:
                shorts.add(stripped.lower())
    return frozenset(shorts)


_SHORT_ALIASES: frozenset = _build_short_aliases()

_VALUE_RE = r"(\d[\d,]*\.?\d*)"
_UNIT_RE  = r"([a-zA-Z/%µμ·²³^\d]{1,20})?"


def _build_pattern(alias: str) -> str:
    """
    Build a regex pattern for a test alias.

    Short aliases: require a delimiter after them (no matching of "22K cells").
    Long aliases:  optional delimiter to handle table-format PDFs.
    """
    escaped = re.escape(alias.strip())
    if alias.strip().lower() in _SHORT_ALIASES:
        return rf"(?<!\d){escaped}\s*[:\-|]\s*{_VALUE_RE}\s*{_UNIT_RE}"
    return rf"\b{escaped}\b\s*[:\-]?\s*{_VALUE_RE}\s*{_UNIT_RE}"


# Pre-compiled {test_id: [(alias, pattern), ...]} — built once at import time.
_PATTERNS: dict = {}


def _init_patterns() -> None:
    for test_id, meta in TEST_CATALOG.items():
        display_name = meta.get("display_name") or test_id
        aliases: list = [display_name] + list(meta.get("aliases") or [])
        compiled: list = []
        for alias in aliases:
            alias = alias.strip()
            if not alias:
                continue
            try:
                compiled.append((alias, re.compile(_build_pattern(alias), re.IGNORECASE)))
            except re.error:
                pass
        _PATTERNS[test_id] = compiled


_init_patterns()




def _score_candidate(
    value_numeric: float,
    unit: str,
    test_id: str,
    matched_alias: str,
    line_type: str,
    catalog_unit: str,
) -> int:
    """
    Score an extracted candidate.  Higher = more likely to be the real result.
    Best-scoring candidate per test_id is kept; anything below 0 is dropped.
    """
    score = 0

    if line_type == LINE_FORMULA:
        score -= 5
    elif line_type == LINE_RANGE:
        score -= 4   # -4 beats any single positive signal (unit match = +3)
    elif line_type in (LINE_RX, LINE_HEADER):
        score -= 4

    if unit and catalog_unit:
        normalised_unit    = _normalize_unit(unit).lower()
        normalised_catalog = _normalize_unit(catalog_unit).lower()
        if normalised_unit == normalised_catalog:
            score += 3
        elif _normalize_unit(unit) and _normalize_unit(unit) != unit:
            score += 1

    limits = HARD_LIMITS.get(test_id)
    if limits:
        hard_min, hard_max = limits
        if value_numeric < hard_min or value_numeric > hard_max:
            score -= 5

    if len(matched_alias) >= 6:
        score += 1

    return score




def _extract_ref_range(line: str, match_end: int) -> Tuple[Optional[float], Optional[float], str]:
    """Extract inline reference range from text after the match position."""
    rest = line[match_end:]
    m = re.search(r"(\d[\d.]*) *[-\u2013\u2014] *(\d[\d.]*)", rest)
    if m:
        lo = _safe_float(m.group(1))
        hi = _safe_float(m.group(2))
        if lo is not None and hi is not None and lo < hi:
            return lo, hi, m.group(0)
    return None, None, ""




def _catalog_ranges(meta: dict) -> Tuple[Optional[float], Optional[float]]:
    ranges    = meta.get("ranges", {}) or {}
    range_obj = ranges.get("all") or ranges.get("male") or {}
    n_min = range_obj.get("min") if range_obj else None
    n_max = range_obj.get("max") if range_obj else None
    if n_min is None:
        n_min = meta.get("normal_min")
    if n_max is None:
        n_max = meta.get("normal_max")
    return (
        _safe_float(n_min) if n_min is not None else None,
        _safe_float(n_max) if n_max is not None else None,
    )


def _extract_tests_from_pages(pages: List[PageContent]) -> List[ExtractedValue]:
    """
    Collect all candidate matches across pages, then return the best-scoring
    candidate per test_id (score must be >= 0).
    """
    candidates: dict = {}

    for page in pages:
        in_rx_section = False

        for line in page.lines:
            line_type = _classify_line(line)

            if line_type == LINE_HEADER:
                in_rx_section = True
                continue

            for test_id, meta in TEST_CATALOG.items():
                catalog_unit = meta.get("unit", "")
                normal_min, normal_max = _catalog_ranges(meta)

                for alias, pattern in _PATTERNS.get(test_id, []):
                    for m in pattern.finditer(line):
                        raw_value = m.group(1)
                        raw_unit  = m.group(2) or ""

                        value = _safe_float(raw_value)
                        if value is None:
                            continue

                        unit_norm = _normalize_unit(raw_unit) if raw_unit else ""

                        score = _score_candidate(
                            value_numeric=value,
                            unit=unit_norm,
                            test_id=test_id,
                            matched_alias=alias,
                            line_type=line_type,
                            catalog_unit=catalog_unit,
                        )

                        ref_min, ref_max, ref_raw = _extract_ref_range(line, m.end())
                        if ref_min is None:
                            ref_min, ref_max, ref_raw = normal_min, normal_max, ""

                        ev = ExtractedValue(
                            test_id=test_id,
                            raw_name=alias,
                            raw_value=raw_value,
                            value_numeric=value,
                            unit=unit_norm,
                            ref_range_raw=ref_raw,
                            ref_min=ref_min,
                            ref_max=ref_max,
                            source_page=page.page_num,
                            source_line=line.strip(),
                            extraction_tier="digital_text",
                        )

                        candidates.setdefault(test_id, []).append((score, ev))

    results: list = []
    for test_id, cands in candidates.items():
        best_score, best_ev = max(cands, key=lambda x: x[0])
        if best_score >= 0:
            results.append(best_ev)

    return results


def _extract_medicines_from_pages(pages: List[PageContent]) -> List[ExtractedMedicine]:
    """
    Context-aware medicine extraction: only fires inside prescription sections
    or on lines that contain dosage/prescription keywords.
    """
    meds: dict = {}

    for page in pages:
        in_rx_section = False

        for line in page.lines:
            line_type = _classify_line(line)

            if line_type == LINE_HEADER:
                in_rx_section = True
                continue

            if not in_rx_section and line_type != LINE_RX:
                continue

            line_lower = line.lower()
            words = re.findall(r"\b[a-z0-9\-]{4,}\b", line_lower)

            for word in words:
                for med_id, meta in MEDICINE_CATALOG.items():
                    if med_id in meds:
                        continue
                    aliases = [med_id] + [a.lower() for a in meta.get("aliases", [])]
                    if word in aliases:
                        meds[med_id] = ExtractedMedicine(
                            id=med_id,
                            name=meta.get("display_name") or med_id,
                            category=meta.get("category"),
                            source_page=page.page_num,
                            source_line=line.strip(),
                        )

    return list(meds.values())




def parse_pages(pages: List[PageContent]) -> ExtractionResult:
    """
    Primary extraction function for the new pipeline.

    Downstream pipeline (in processor.py):
      medical_validator.validate(result)  →  ontology.normalize(result)  →  LLM
    """
    result = ExtractionResult(pages=pages)
    result.values    = _extract_tests_from_pages(pages)
    result.medicines = _extract_medicines_from_pages(pages)
    return result




def extract_tests(text: str) -> List[Dict]:
    """
    Backward-compatible wrapper.  Accepts a flat string, returns List[Dict].
    Validator/ontology steps are NOT applied here — they run in processor.py.
    """
    if not text or not text.strip():
        return []

    lines = [ln for ln in text.splitlines() if ln.strip()]
    page  = PageContent(page_num=1, lines=lines, raw_text=text)
    result = parse_pages([page])

    return [
        {
            "id":         v.test_id,
            "name":       v.raw_name,
            "value":      v.value_numeric,
            "unit":       v.unit,
            "normal_min": v.ref_min,
            "normal_max": v.ref_max,
        }
        for v in result.values
    ]


def extract_medicines(text: str) -> List[Dict]:
    """
    Backward-compatible medicine extractor — word-match-anywhere approach.
    The production pipeline uses _extract_medicines_from_pages() via parse_pages().
    """
    if not text or not text.strip():
        return []

    normalized = _normalize_text(text)
    meds: dict = {}
    words = re.findall(r"\b[a-z0-9\-]{4,}\b", normalized)

    for word in words:
        for med_id, meta in MEDICINE_CATALOG.items():
            if med_id in meds:
                continue
            aliases = [med_id] + [a.lower() for a in meta.get("aliases", [])]
            if word in aliases:
                meds[med_id] = {
                    "id":       med_id,
                    "name":     meta.get("display_name") or med_id,
                    "category": meta.get("category"),
                }

    return list(meds.values())


def parse_medical_text(text: str) -> Dict:
    """
    Backward-compatible wrapper returning {"tests": [...], "medicines": [...]}.
    """
    if not text or not text.strip():
        return {"tests": [], "medicines": []}
    return {
        "tests":     extract_tests(text),
        "medicines": extract_medicines(text),
    }
