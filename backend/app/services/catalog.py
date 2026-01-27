import json
import os
from typing import Dict

BASE_PATH = os.path.join(os.path.dirname(__file__), "..", "catalog")

def _load_json(filename: str) -> Dict:
    path = os.path.join(BASE_PATH, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

TEST_CATALOG = _load_json("tests.json")
MEDICINE_CATALOG = _load_json("medicines.json")
SYNONYMS = _load_json("synonyms.json")
UNITS = _load_json("units.json")


def reload_catalog():
    global TEST_CATALOG, MEDICINE_CATALOG, SYNONYMS, UNITS
    TEST_CATALOG = _load_json("tests.json")
    MEDICINE_CATALOG = _load_json("medicines.json")
    SYNONYMS = _load_json("synonyms.json")
    UNITS = _load_json("units.json")
