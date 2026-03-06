#!/usr/bin/env python3
"""
Index medical catalog data into PostgreSQL (pgvector) for RAG retrieval.

Converts tests.json + medicines.json into embeddable knowledge chunks,
embeds them via Jina AI, and upserts into the medical_knowledge table.

Usage:
    python scripts/index_catalogs.py              # index everything
    python scripts/index_catalogs.py --tests-only  # only tests
    python scripts/index_catalogs.py --meds-only   # only medicines
    python scripts/index_catalogs.py --dry-run     # preview chunks
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Add backend to path so we can import app modules
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

CATALOG_DIR = BACKEND_DIR / "app" / "catalog"


def _load_json(filename: str) -> Dict:
    path = CATALOG_DIR / filename
    if not path.exists():
        log.warning("File not found: %s", path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_test_chunks(tests: Dict) -> List[Tuple[str, Dict]]:
    """Build knowledge chunks from tests.json.

    Each test becomes 1-2 chunks:
    - A factual chunk (what is it, normal range, unit)
    - An interpretation chunk (meaning, causes, what abnormal means)
    """
    chunks = []
    for key, meta in tests.items():
        if key.startswith("_"):
            continue
        if not isinstance(meta, dict):
            continue

        name = meta.get("display_name", key)
        category = meta.get("category", "unknown")
        unit = meta.get("unit", "")
        nmin = meta.get("normal_min")
        nmax = meta.get("normal_max")
        meaning = meta.get("meaning", "")
        normal_meaning = meta.get("normal_meaning", "")
        causes = meta.get("common_causes", [])
        aliases = meta.get("aliases", [])

        # Chunk 1: Factual
        range_str = ""
        if nmin is not None and nmax is not None:
            range_str = f"Normal range: {nmin}–{nmax} {unit}."
        elif nmax is not None:
            range_str = f"Normal: below {nmax} {unit}."

        alias_str = ""
        if aliases:
            alias_str = f" Also known as: {', '.join(aliases[:4])}."

        factual = (
            f"{name} is a {category} lab test.{alias_str} "
            f"Measured in {unit}. {range_str}"
        ).strip()

        chunks.append((
            factual,
            {"source": "catalog_tests", "test_id": key, "category": category, "chunk_type": "factual"},
        ))

        # Chunk 2: Clinical interpretation
        if meaning or causes:
            causes_str = ""
            if causes:
                causes_str = f" Common causes of abnormality: {', '.join(causes[:5])}."

            clinical = (
                f"{name}: {meaning} "
                f"{normal_meaning}{causes_str}"
            ).strip()

            chunks.append((
                clinical,
                {"source": "catalog_tests", "test_id": key, "category": category, "chunk_type": "clinical"},
            ))

    return chunks


def build_medicine_chunks(medicines: Dict) -> List[Tuple[str, Dict]]:
    """Build knowledge chunks from medicines.json."""
    chunks = []
    for key, meta in medicines.items():
        if not isinstance(meta, dict):
            continue

        name = meta.get("display_name", key)
        category = meta.get("category", "unknown")
        aliases = meta.get("aliases", [])
        purpose = meta.get("purpose", "")

        brands = [a for a in aliases if a[0].isupper()] if aliases else []
        brand_str = f" Brand names: {', '.join(brands[:5])}." if brands else ""

        purpose_str = ""
        if purpose:
            # Truncate long OpenFDA indications
            if len(purpose) > 200:
                purpose = purpose[:200].rsplit(" ", 1)[0] + "..."
            purpose_str = f" {purpose}"

        chunk = (
            f"{name} is a {category} medication.{brand_str}{purpose_str}"
        ).strip()

        chunks.append((
            chunk,
            {"source": "catalog_medicines", "med_id": key, "category": category},
        ))

    return chunks


def index_chunks(
    chunks: List[Tuple[str, Dict]],
    dry_run: bool = False,
) -> int:
    """Index chunks into PostgreSQL via retrieval service."""
    if not chunks:
        log.info("No chunks to index.")
        return 0

    documents = [c[0] for c in chunks]
    metadatas = [c[1] for c in chunks]

    if dry_run:
        log.info("[DRY-RUN] Would index %d chunks. Samples:", len(chunks))
        for doc, meta in chunks[:5]:
            log.info("  [%s] %s", meta.get("chunk_type", meta.get("category")), doc[:100])
        return len(chunks)

    from app.services.retrieval import index_documents
    return index_documents(documents, metadatas)


def main():
    parser = argparse.ArgumentParser(description="Index catalog data into PostgreSQL (pgvector)")
    parser.add_argument("--tests-only", action="store_true", help="Only index tests")
    parser.add_argument("--meds-only", action="store_true", help="Only index medicines")
    parser.add_argument("--dry-run", action="store_true", help="Preview chunks only")
    args = parser.parse_args()

    all_chunks = []

    if not args.meds_only:
        tests = _load_json("tests.json")
        test_chunks = build_test_chunks(tests)
        log.info("Built %d test knowledge chunks", len(test_chunks))
        all_chunks.extend(test_chunks)

    if not args.tests_only:
        medicines = _load_json("medicines.json")
        med_chunks = build_medicine_chunks(medicines)
        log.info("Built %d medicine knowledge chunks", len(med_chunks))
        all_chunks.extend(med_chunks)

    log.info("Total chunks: %d", len(all_chunks))
    indexed = index_chunks(all_chunks, dry_run=args.dry_run)
    log.info("Indexed: %d", indexed)


if __name__ == "__main__":
    main()
