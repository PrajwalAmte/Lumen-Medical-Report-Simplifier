import re
from typing import Dict, List, Optional
from app.services.catalog import TEST_CATALOG, MEDICINE_CATALOG, SYNONYMS, UNITS


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


def _safe_float(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None


def extract_tests(text: str) -> List[Dict]:
    text = _normalize_text(text)
    tests = []

    for test_id, meta in TEST_CATALOG.items():
        display_name = meta.get("display_name") or test_id
        aliases = [display_name.lower()] + [a.lower() for a in meta.get("aliases", [])]
        
        unit = meta.get("unit", "")
        units = meta.get("units", [unit] if unit else [])

        for name in aliases:
            pattern = rf"{re.escape(name)}\s*[:\-]?\s*(\d+\.?\d*)\s*([a-zA-Z/^\d]+)?"
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                raw_value = match.group(1)
                raw_unit = match.group(2) or units[0] if units else ""

                value = _safe_float(raw_value)
                unit_normalized = _normalize_unit(raw_unit)

                ranges = meta.get("ranges", {})
                range_obj = ranges.get("all") or ranges.get("male") or {}
                normal_min = range_obj.get("min") or meta.get("normal_min")
                normal_max = range_obj.get("max") or meta.get("normal_max")

                tests.append({
                    "id": test_id,
                    "name": display_name,
                    "value": value,
                    "unit": unit_normalized,
                    "normal_min": normal_min,
                    "normal_max": normal_max
                })

    return tests


def extract_medicines(text: str) -> List[Dict]:
    text = _normalize_text(text)
    meds = {}

    words = re.findall(r"\b[a-z0-9\-]{4,}\b", text)

    for word in words:
        for med_id, meta in MEDICINE_CATALOG.items():
            aliases = [med_id] + [a.lower() for a in meta.get("aliases", [])]
            if word in aliases:
                display_name = meta.get("display_name") or med_id
                meds[med_id] = {
                    "id": med_id,
                    "name": display_name,
                    "category": meta.get("category")
                }

    return list(meds.values())


def parse_medical_text(text: str) -> Dict:
    return {
        "tests": extract_tests(text),
        "medicines": extract_medicines(text)
    }
