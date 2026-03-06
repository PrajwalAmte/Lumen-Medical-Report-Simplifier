#!/usr/bin/env python3
"""
Master catalog builder — orchestrates all ingestion and generates derived files.

Usage:
    python scripts/build_catalogs.py --rxnorm             # pull drugs from RxNorm
    python scripts/build_catalogs.py --rxnorm --enrich     # + OpenFDA indications
    python scripts/build_catalogs.py --loinc /path/to/Loinc.csv  # pull tests from LOINC
    python scripts/build_catalogs.py --synonyms --units    # regenerate derived files
    python scripts/build_catalogs.py --all --loinc /path/to/Loinc.csv  # everything
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOG_DIR = SCRIPT_DIR.parent / "app" / "catalog"

# Add backend to path so scripts can import each other
sys.path.insert(0, str(SCRIPT_DIR))


def _load_json(path: Path) -> Dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    log.info("Wrote %s (%d entries)", path, len(data))


def build_synonyms() -> None:
    """Auto-generate synonyms.json from tests.json + medicines.json aliases."""
    tests = _load_json(CATALOG_DIR / "tests.json")
    meds = _load_json(CATALOG_DIR / "medicines.json")
    synonyms: Dict[str, str] = {}

    # Skip metadata key
    for test_key, meta in tests.items():
        if test_key.startswith("_"):
            continue
        for alias in meta.get("aliases", []):
            syn_key = alias.lower().strip()
            if syn_key and syn_key != test_key:
                synonyms[syn_key] = test_key

    for med_key, meta in meds.items():
        for alias in meta.get("aliases", []):
            syn_key = alias.lower().strip()
            if syn_key and syn_key != med_key:
                synonyms[syn_key] = med_key

    _write_json(CATALOG_DIR / "synonyms.json", synonyms)
    log.info(
        "Synonyms: %d test aliases + medicine aliases",
        len(synonyms),
    )


# Unit normalization table — maps variant spellings to canonical units.
UNIT_NORMALIZATIONS: Dict[str, str] = {
    # Volume
    "g/dl": "g/dL", "gm/dl": "g/dL", "g / dl": "g/dL", "grams/dl": "g/dL",
    "mg/dl": "mg/dL", "mg / dl": "mg/dL",
    "ug/dl": "μg/dL", "mcg/dl": "μg/dL", "µg/dl": "μg/dL",
    "ng/ml": "ng/mL", "ng / ml": "ng/mL",
    "pg/ml": "pg/mL", "pg / ml": "pg/mL",
    "ng/dl": "ng/dL", "ng / dl": "ng/dL",
    "mg/l": "mg/L", "mg / l": "mg/L",
    "ug/l": "μg/L", "mcg/l": "μg/L",
    "iu/ml": "IU/mL", "iu / ml": "IU/mL",
    "u/ml": "U/mL",
    "miu/ml": "mIU/mL", "miu / ml": "mIU/mL", "µiu/ml": "μIU/mL",
    "uiu/ml": "μIU/mL",
    # Cell counts
    "cells/mcl": "cells/mcL", "cells / mcl": "cells/mcL",
    "cells/ul": "cells/mcL", "/mcl": "cells/mcL", "/ul": "cells/mcL",
    "cells/cumm": "cells/mcL", "/cumm": "cells/mcL", "cells/cmm": "cells/mcL",
    "x10^3/ul": "×10³/mcL", "x10^3/mcl": "×10³/mcL", "thou/ul": "×10³/mcL",
    "x10^6/ul": "million/mcL", "x10^6/mcl": "million/mcL", "mill/ul": "million/mcL",
    "million/ul": "million/mcL", "m/ul": "million/mcL",
    "lakh/mcl": "lakh/mcL", "lakhs/mcl": "lakh/mcL",
    "x10^9/l": "×10⁹/L",
    "x10^12/l": "×10¹²/L",
    # Enzyme
    "u/l": "U/L", "iu/l": "U/L", "u / l": "U/L",
    # Percentage
    "percent": "%",
    # Time
    "sec": "seconds", "secs": "seconds",
    "mm/hr": "mm/hr", "mm/1hr": "mm/hr", "mm / hr": "mm/hr",
    # Hormones
    "uiu/ml": "μIU/mL", "µiu/ml": "μIU/mL",
    "pmol/l": "pmol/L",
    "nmol/l": "nmol/L",
    "umol/l": "μmol/L", "µmol/l": "μmol/L", "mcmol/l": "μmol/L",
    # Misc
    "meq/l": "mEq/L", "meq / l": "mEq/L", "mmol/l": "mmol/L",
    "ml/min/1.73m2": "mL/min/1.73m²", "ml/min/1.73m^2": "mL/min/1.73m²",
    "u/g hb": "U/g Hb",
    "g/dl": "g/dL",
    "fl": "fL",
    "pg": "pg",
}


def build_units() -> None:
    """Generate units.json normalization table."""
    # Start with our curated table
    units = dict(UNIT_NORMALIZATIONS)

    # Also scan tests.json for units and make sure each unit maps to itself
    tests = _load_json(CATALOG_DIR / "tests.json")
    for meta in tests.values():
        if isinstance(meta, dict):
            unit = meta.get("unit", "")
            if unit and unit.lower() not in units:
                units[unit.lower()] = unit

    _write_json(CATALOG_DIR / "units.json", units)


def run_rxnorm(enrich: bool = False, dry_run: bool = False) -> None:
    """Import and run RxNorm ingestion."""
    from ingest_rxnorm import run_ingestion
    run_ingestion(enrich=enrich, dry_run=dry_run)


def run_loinc(csv_path: str, merge: bool = True, dry_run: bool = False) -> None:
    """Import and run LOINC ingestion."""
    from ingest_loinc import parse_loinc_csv, write_catalog
    tests = parse_loinc_csv(csv_path)
    write_catalog(tests, merge=merge, dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(description="Master catalog builder")
    parser.add_argument("--rxnorm", action="store_true", help="Pull drugs from RxNorm API")
    parser.add_argument("--enrich", action="store_true", help="Enrich drugs with OpenFDA (slower)")
    parser.add_argument("--loinc", type=str, help="Path to Loinc.csv")
    parser.add_argument("--synonyms", action="store_true", help="Regenerate synonyms.json")
    parser.add_argument("--units", action="store_true", help="Regenerate units.json")
    parser.add_argument("--all", action="store_true", help="Run everything (needs --loinc for tests)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if not any([args.rxnorm, args.loinc, args.synonyms, args.units, args.all]):
        parser.print_help()
        sys.exit(1)

    if args.all or args.rxnorm:
        log.info("═══ RxNorm Drug Ingestion ═══")
        run_rxnorm(enrich=args.enrich or args.all, dry_run=args.dry_run)

    if args.loinc or (args.all and args.loinc):
        log.info("═══ LOINC Test Ingestion ═══")
        run_loinc(args.loinc, merge=True, dry_run=args.dry_run)

    if args.all or args.synonyms:
        log.info("═══ Building Synonyms ═══")
        if not args.dry_run:
            build_synonyms()
        else:
            log.info("[DRY-RUN] Would rebuild synonyms.json")

    if args.all or args.units:
        log.info("═══ Building Units ═══")
        if not args.dry_run:
            build_units()
        else:
            log.info("[DRY-RUN] Would rebuild units.json")

    log.info("═══ Done ═══")


if __name__ == "__main__":
    main()
