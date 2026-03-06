#!/usr/bin/env python3
"""
Ingest lab-test data from LOINC CSV → tests.json catalog.

LOINC is the international standard for lab-test identification.
Download the CSV for free from https://loinc.org/downloads/ (requires free account).

Expected input: Loinc.csv (the main table from the LOINC release).

Usage:
    python scripts/ingest_loinc.py --loinc-csv /path/to/Loinc.csv
    python scripts/ingest_loinc.py --loinc-csv /path/to/Loinc.csv --merge   # merge into existing tests.json
    python scripts/ingest_loinc.py --loinc-csv /path/to/Loinc.csv --dry-run
"""

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

CATALOG_DIR = Path(__file__).resolve().parent.parent / "app" / "catalog"

# ---------------------------------------------------------------------------
# Filters: we only want common quantitative lab tests on serum/blood/urine.
# LOINC has 100k+ codes; we filter aggressively.
# ---------------------------------------------------------------------------
ALLOWED_SYSTEMS = {
    "ser", "plas", "bld", "ser/plas", "ser+plas", "urine", "ur",
    "bld.v", "rbc", "wbc", "blood",
}

ALLOWED_PROPERTY = {
    "mcnc", "scnc", "ncnc", "mrat", "ccnc", "num", "enz",
    "mfr", "vfr", "acnc", "mcnt", "time", "threshold",
}

# Components we definitely want (partial match on COMPONENT field)
PRIORITY_COMPONENTS = {
    "hemoglobin", "erythrocytes", "leukocytes", "platelets",
    "hematocrit", "glucose", "creatinine", "urea", "bilirubin",
    "cholesterol", "triglyceride", "hdl", "ldl",
    "aspartate aminotransferase", "alanine aminotransferase",
    "alkaline phosphatase", "albumin", "protein",
    "thyrotropin", "thyroxine", "triiodothyronine",
    "hemoglobin a1c", "sodium", "potassium", "chloride",
    "calcium", "phosphate", "magnesium", "iron", "ferritin",
    "vitamin d", "vitamin b12", "folate",
    "c reactive protein", "prothrombin", "inr",
    "troponin", "prostate specific ag",
}

# Indian-lab reference ranges aren't in LOINC — we keep a curated table.
# These override LOINC data; the script merges them.
REFERENCE_RANGES: Dict[str, Dict[str, Any]] = {
    "hemoglobin": {"normal_min": 12.0, "normal_max": 17.0, "unit": "g/dL",
                   "ranges": {"male": {"min": 13.0, "max": 17.0}, "female": {"min": 12.0, "max": 15.5}}},
    "erythrocytes": {"normal_min": 4.0, "normal_max": 5.5, "unit": "million/mcL"},
    "leukocytes": {"normal_min": 4000, "normal_max": 11000, "unit": "cells/mcL"},
    "platelets": {"normal_min": 150000, "normal_max": 450000, "unit": "cells/mcL"},
    "glucose": {"normal_min": 70, "normal_max": 100, "unit": "mg/dL"},
    "creatinine": {"normal_min": 0.6, "normal_max": 1.3, "unit": "mg/dL"},
    "urea nitrogen": {"normal_min": 7, "normal_max": 20, "unit": "mg/dL"},
    "bilirubin.total": {"normal_min": 0.1, "normal_max": 1.2, "unit": "mg/dL"},
    "cholesterol": {"normal_min": 0, "normal_max": 200, "unit": "mg/dL"},
    "triglyceride": {"normal_min": 0, "normal_max": 150, "unit": "mg/dL"},
    "cholesterol in hdl": {"normal_min": 40, "normal_max": 60, "unit": "mg/dL"},
    "cholesterol in ldl": {"normal_min": 0, "normal_max": 100, "unit": "mg/dL"},
    "aspartate aminotransferase": {"normal_min": 0, "normal_max": 40, "unit": "U/L"},
    "alanine aminotransferase": {"normal_min": 0, "normal_max": 40, "unit": "U/L"},
    "alkaline phosphatase": {"normal_min": 44, "normal_max": 147, "unit": "U/L"},
    "albumin": {"normal_min": 3.5, "normal_max": 5.0, "unit": "g/dL"},
    "protein": {"normal_min": 6.0, "normal_max": 8.3, "unit": "g/dL"},
    "thyrotropin": {"normal_min": 0.4, "normal_max": 4.0, "unit": "μIU/mL"},
    "hemoglobin a1c": {"normal_min": 4.0, "normal_max": 5.6, "unit": "%"},
    "sodium": {"normal_min": 136, "normal_max": 145, "unit": "mEq/L"},
    "potassium": {"normal_min": 3.5, "normal_max": 5.0, "unit": "mEq/L"},
    "calcium": {"normal_min": 8.5, "normal_max": 10.5, "unit": "mg/dL"},
    "iron": {"normal_min": 50, "normal_max": 175, "unit": "μg/dL"},
    "ferritin": {"normal_min": 15, "normal_max": 400, "unit": "ng/mL"},
    "c reactive protein": {"normal_min": 0, "normal_max": 10, "unit": "mg/L"},
}


def _normalize_key(component: str) -> str:
    """Turn LOINC COMPONENT into a snake_case catalog key."""
    key = component.lower().strip()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return key


def _is_relevant(row: Dict[str, str]) -> bool:
    """Return True if this LOINC row is a lab test we care about."""
    status = row.get("STATUS", "")
    if status not in ("ACTIVE", ""):
        return False

    system = row.get("SYSTEM", "").lower()
    if not any(s in system for s in ALLOWED_SYSTEMS):
        return False

    prop = row.get("PROPERTY", "").lower()
    if prop and prop not in ALLOWED_PROPERTY:
        return False

    # Scale must be quantitative
    scale = row.get("SCALE_TYP", "").lower()
    if scale not in ("qn", ""):
        return False

    return True


def _is_priority(component: str) -> bool:
    """Check if this component matches a priority pattern."""
    comp_lower = component.lower()
    return any(p in comp_lower for p in PRIORITY_COMPONENTS)


def parse_loinc_csv(csv_path: str, max_tests: int = 300) -> Dict[str, Dict]:
    """Parse Loinc.csv and return filtered tests dict."""
    tests: Dict[str, Dict] = {}
    priority: Dict[str, Dict] = {}
    total_rows = 0
    relevant_rows = 0

    log.info("Reading %s ...", csv_path)

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            if not _is_relevant(row):
                continue
            relevant_rows += 1

            component = row.get("COMPONENT", "").strip()
            if not component:
                continue

            loinc_num = row.get("LOINC_NUM", "")
            long_name = row.get("LONG_COMMON_NAME", "") or row.get("SHORTNAME", component)
            system = row.get("SYSTEM", "")
            unit = row.get("EXAMPLE_UCUM_UNITS", "") or row.get("SUBMITTED_UNITS", "")

            key = _normalize_key(component)
            if key in tests:
                continue

            entry: Dict[str, Any] = {
                "display_name": long_name.strip(),
                "loinc_code": loinc_num,
                "category": _infer_category(component, system),
                "unit": unit,
                "aliases": _build_aliases(component, long_name, key),
            }

            # Merge known reference ranges
            ref = _find_reference(component)
            if ref:
                entry.update(ref)
            else:
                entry["normal_min"] = None
                entry["normal_max"] = None

            entry["meaning"] = f"Lab measurement of {component.lower()} in {system.lower()}."
            entry["normal_meaning"] = f"Your {component.lower()} level is within normal range."

            if _is_priority(component):
                priority[key] = entry
            else:
                tests[key] = entry

    log.info(
        "Parsed %d total rows, %d relevant, %d priority, %d other",
        total_rows, relevant_rows, len(priority), len(tests),
    )

    # Priority tests first, then fill up to max_tests
    result = dict(priority)
    remaining = max_tests - len(result)
    for k, v in list(tests.items())[:remaining]:
        if k not in result:
            result[k] = v

    log.info("Final test catalog: %d entries", len(result))
    return result


def _infer_category(component: str, system: str) -> str:
    """Infer test category from LOINC fields."""
    comp = component.lower()
    sys_lower = system.lower()

    if "urine" in sys_lower or "ur" == sys_lower:
        return "urine"
    if any(w in comp for w in ["hemoglobin", "erythrocyte", "leukocyte", "platelet", "hematocrit", "mcv", "mch", "rbc", "wbc"]):
        return "cbc"
    if any(w in comp for w in ["bilirubin", "transaminase", "aminotransferase", "phosphatase", "albumin", "globulin", "ggt"]):
        return "lft"
    if any(w in comp for w in ["creatinine", "urea", "uric acid", "gfr"]):
        return "kft"
    if any(w in comp for w in ["cholesterol", "triglyceride", "hdl", "ldl", "vldl", "lipoprotein"]):
        return "lipid"
    if any(w in comp for w in ["glucose", "hemoglobin a1c", "insulin"]):
        return "diabetes"
    if any(w in comp for w in ["thyrotropin", "thyroxine", "triiodothyronine", "thyroid"]):
        return "thyroid"
    if any(w in comp for w in ["iron", "ferritin", "transferrin", "tibc"]):
        return "iron_studies"
    if any(w in comp for w in ["troponin", "natriuretic", "ck-mb", "cpk"]):
        return "cardiac"
    if any(w in comp for w in ["prothrombin", "fibrinogen", "d-dimer", "inr", "aptt"]):
        return "coagulation"
    if any(w in comp for w in ["vitamin", "cobalamin", "folate", "calciferol"]):
        return "vitamins"
    if any(w in comp for w in ["sodium", "potassium", "chloride", "calcium", "phosph", "magnesium", "bicarbonate"]):
        return "electrolytes"
    return "other"


def _build_aliases(component: str, long_name: str, key: str) -> List[str]:
    """Generate search aliases from LOINC names."""
    aliases = set()
    # Add the component itself
    aliases.add(component.lower())
    # Add individual words from long_name if meaningful
    for word in long_name.lower().split():
        if len(word) > 3 and word not in ("mass", "volume", "moles", "with", "from", "serum", "plasma"):
            aliases.add(word)
    # Remove the key itself
    aliases.discard(key)
    return sorted(aliases)[:6]  # cap at 6


def _find_reference(component: str) -> Optional[Dict]:
    """Look up curated reference ranges for a LOINC component."""
    comp = component.lower()
    for pattern, ref in REFERENCE_RANGES.items():
        if pattern in comp:
            return {k: v for k, v in ref.items()}
    return None


def write_catalog(
    tests: Dict[str, Dict],
    merge: bool = False,
    dry_run: bool = False,
) -> None:
    """Write tests dict to tests.json, optionally merging with existing."""
    out_path = CATALOG_DIR / "tests.json"

    if merge and out_path.exists():
        with open(out_path, "r") as f:
            existing = json.load(f)
        log.info("Merging with existing catalog (%d entries)", len(existing))
        # Existing entries take priority (they have curated ranges)
        for key, entry in tests.items():
            if key not in existing:
                existing[key] = entry
        tests = existing
        log.info("After merge: %d entries", len(tests))

    if dry_run:
        log.info("[DRY-RUN] Would write %d test entries", len(tests))
        for k in list(tests.keys())[:10]:
            log.info("  %s: %s", k, tests[k].get("display_name", "?"))
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tests, f, indent=2, ensure_ascii=False)
    log.info("Wrote %s (%d entries)", out_path, len(tests))

    # Also update synonyms
    _update_synonyms(tests)


def _update_synonyms(tests: Dict[str, Dict]) -> None:
    """Merge test aliases into synonyms.json."""
    syn_path = CATALOG_DIR / "synonyms.json"
    synonyms: Dict[str, str] = {}
    if syn_path.exists():
        with open(syn_path, "r") as f:
            synonyms = json.load(f)

    added = 0
    for test_key, meta in tests.items():
        for alias in meta.get("aliases", []):
            alias_lower = alias.lower().strip()
            if alias_lower and alias_lower not in synonyms:
                synonyms[alias_lower] = test_key
                added += 1

    with open(syn_path, "w", encoding="utf-8") as f:
        json.dump(synonyms, f, indent=2, ensure_ascii=False, sort_keys=True)
    log.info("Updated synonyms.json: +%d test aliases", added)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest LOINC CSV → tests.json",
        epilog="Download Loinc.csv free from https://loinc.org/downloads/",
    )
    parser.add_argument(
        "--loinc-csv",
        required=True,
        help="Path to Loinc.csv from LOINC release",
    )
    parser.add_argument(
        "--max-tests",
        type=int,
        default=300,
        help="Maximum number of tests to include (default: 300)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge into existing tests.json (existing entries take priority)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing files",
    )
    args = parser.parse_args()

    if not Path(args.loinc_csv).exists():
        log.error("File not found: %s", args.loinc_csv)
        log.error("Download Loinc.csv from https://loinc.org/downloads/ (free account)")
        sys.exit(1)

    tests = parse_loinc_csv(args.loinc_csv, max_tests=args.max_tests)
    write_catalog(tests, merge=args.merge, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
