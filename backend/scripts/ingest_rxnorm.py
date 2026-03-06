#!/usr/bin/env python3
"""
Ingest drug data from RxNorm REST API + OpenFDA → medicines.json + synonyms enrichment.

RxNorm: https://rxnav.nlm.nih.gov/REST  (free, no auth)
OpenFDA: https://api.fda.gov/drug/label   (free, no auth)

Usage:
    python scripts/ingest_rxnorm.py                         # default: all classes
    python scripts/ingest_rxnorm.py --classes antibiotics analgesics
    python scripts/ingest_rxnorm.py --enrich                # also pull indications from OpenFDA
    python scripts/ingest_rxnorm.py --dry-run               # preview without writing files
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

CATALOG_DIR = Path(__file__).resolve().parent.parent / "app" / "catalog"

# ---------------------------------------------------------------------------
# ATC class IDs → our category labels
# We pick the classes most relevant to Indian prescriptions.
# ---------------------------------------------------------------------------
ATC_CLASSES: Dict[str, Dict[str, str]] = {
    # Antibiotics
    "J01CA": {"category": "antibiotic", "label": "Penicillins (broad)"},
    "J01CR": {"category": "antibiotic", "label": "Penicillin + inhibitor combos"},
    "J01DC": {"category": "antibiotic", "label": "2nd-gen cephalosporins"},
    "J01DD": {"category": "antibiotic", "label": "3rd-gen cephalosporins"},
    "J01FA": {"category": "antibiotic", "label": "Macrolides"},
    "J01MA": {"category": "antibiotic", "label": "Fluoroquinolones"},
    "J01AA": {"category": "antibiotic", "label": "Tetracyclines"},
    "J01EE": {"category": "antibiotic", "label": "Sulfonamide combos"},
    "J01XD": {"category": "antibiotic", "label": "Nitroimidazoles (metronidazole)"},
    # Analgesics / NSAIDs
    "N02BE": {"category": "analgesic", "label": "Anilides (paracetamol)"},
    "N02BA": {"category": "analgesic", "label": "Salicylates"},
    "M01AE": {"category": "nsaid", "label": "Propionic acid NSAIDs"},
    "M01AB": {"category": "nsaid", "label": "Acetic acid NSAIDs"},
    "M01AH": {"category": "nsaid", "label": "COX-2 inhibitors"},
    # Antidiabetics
    "A10BA": {"category": "antidiabetic", "label": "Biguanides (metformin)"},
    "A10BB": {"category": "antidiabetic", "label": "Sulfonylureas"},
    "A10BH": {"category": "antidiabetic", "label": "DPP-4 inhibitors"},
    "A10BK": {"category": "antidiabetic", "label": "SGLT2 inhibitors"},
    "A10AE": {"category": "antidiabetic", "label": "Long-acting insulins"},
    # Antihypertensives
    "C09AA": {"category": "antihypertensive", "label": "ACE inhibitors"},
    "C09CA": {"category": "antihypertensive", "label": "ARBs"},
    "C08CA": {"category": "antihypertensive", "label": "Dihydropyridine CCBs"},
    "C07AB": {"category": "antihypertensive", "label": "Beta-blockers (selective)"},
    "C03AA": {"category": "diuretic", "label": "Thiazide diuretics"},
    "C03CA": {"category": "diuretic", "label": "Loop diuretics"},
    # Lipid-lowering
    "C10AA": {"category": "statin", "label": "HMG-CoA reductase inhibitors"},
    "C10AB": {"category": "lipid_lowering", "label": "Fibrates"},
    # GI / acid suppression
    "A02BC": {"category": "ppi", "label": "Proton pump inhibitors"},
    "A02BA": {"category": "h2_blocker", "label": "H2-receptor antagonists"},
    "A03FA": {"category": "prokinetic", "label": "Prokinetics"},
    # Antihistamines
    "R06AE": {"category": "antihistamine", "label": "Piperazine antihistamines"},
    "R06AX": {"category": "antihistamine", "label": "Other antihistamines"},
    # Corticosteroids
    "H02AB": {"category": "corticosteroid", "label": "Glucocorticoids"},
    # Thyroid
    "H03AA": {"category": "thyroid", "label": "Thyroid hormones"},
    "H03BB": {"category": "antithyroid", "label": "Antithyroid agents"},
    # Antiplatelets / anticoagulants
    "B01AC": {"category": "antiplatelet", "label": "Platelet aggregation inhibitors"},
    "B01AA": {"category": "anticoagulant", "label": "Vitamin K antagonists"},
    "B01AF": {"category": "anticoagulant", "label": "Direct Xa inhibitors"},
    # Bronchodilators
    "R03AC": {"category": "bronchodilator", "label": "Selective beta-2 agonists"},
    "R03BB": {"category": "bronchodilator", "label": "Anticholinergic inhalers"},
    "R03BA": {"category": "inhaled_corticosteroid", "label": "Inhaled corticosteroids"},
    # Antidepressants / anxiolytics
    "N06AB": {"category": "antidepressant", "label": "SSRIs"},
    "N05BA": {"category": "anxiolytic", "label": "Benzodiazepines"},
    # Antiepileptics
    "N03AX": {"category": "antiepileptic", "label": "Other antiepileptics"},
    # Supplements
    "B03AA": {"category": "supplement", "label": "Iron (oral)"},
    "A11CC": {"category": "supplement", "label": "Vitamin D"},
    "B03BA": {"category": "supplement", "label": "Vitamin B12"},
    "A11GA": {"category": "supplement", "label": "Ascorbic acid (Vit C)"},
    "B03BB": {"category": "supplement", "label": "Folic acid"},
    "A12AA": {"category": "supplement", "label": "Calcium"},
    # Antifungals
    "J02AC": {"category": "antifungal", "label": "Triazole antifungals"},
    "D01BA": {"category": "antifungal", "label": "Systemic antifungals"},
    # Antivirals
    "J05AE": {"category": "antiviral", "label": "Protease inhibitors"},
    "J05AF": {"category": "antiviral", "label": "NRTIs"},
    # Antimalarials
    "P01BA": {"category": "antimalarial", "label": "Aminoquinolines"},
    # Antiemetics
    "A04AA": {"category": "antiemetic", "label": "Serotonin antagonists"},
    # Muscle relaxants
    "M03BX": {"category": "muscle_relaxant", "label": "Other muscle relaxants"},
}

# Indian brand-name mapping (generic → common Indian brands).
# RxNorm only carries US brands; we add Indian ones manually.
INDIAN_BRANDS: Dict[str, List[str]] = {
    "amoxicillin": ["Amoxil", "Mox", "Novamox"],
    "amoxicillin / clavulanate": ["Augmentin", "Clavam", "Moxikind-CV"],
    "azithromycin": ["Azee", "Zithromax", "Azithral"],
    "cefixime": ["Taxim-O", "Cefix", "Zifi"],
    "cefpodoxime": ["Cepodem", "Cefpod"],
    "ciprofloxacin": ["Ciplox", "Cifran"],
    "levofloxacin": ["Levoflox", "Levomac", "Glevo"],
    "ofloxacin": ["Oflox", "Zanocin"],
    "doxycycline": ["Doxy-1", "Doxt-SL"],
    "metronidazole": ["Flagyl", "Metrogyl"],
    "cotrimoxazole": ["Bactrim", "Septran"],
    "acetaminophen": ["Crocin", "Calpol", "Dolo 650"],
    "ibuprofen": ["Brufen", "Ibugesic"],
    "diclofenac": ["Voveran", "Dynapar"],
    "aceclofenac": ["Zerodol", "Hifenac"],
    "naproxen": ["Naprosyn", "Xenobid"],
    "aspirin": ["Ecosprin", "Disprin"],
    "metformin": ["Glycomet", "Glyciphage"],
    "glimepiride": ["Amaryl", "Glimisave"],
    "gliclazide": ["Diamicron", "Glizid"],
    "sitagliptin": ["Januvia", "Istavel"],
    "vildagliptin": ["Galvus", "Zomelis"],
    "empagliflozin": ["Jardiance"],
    "dapagliflozin": ["Forxiga", "Oxra"],
    "insulin glargine": ["Lantus", "Basalog", "Glaritus"],
    "enalapril": ["Envas", "Enam"],
    "ramipril": ["Cardace", "Ramistar"],
    "losartan": ["Losar", "Losacar", "Repace"],
    "telmisartan": ["Telma", "Telmikind"],
    "olmesartan": ["Olmy", "Olmetec"],
    "amlodipine": ["Amlong", "Amlip", "Stamlo"],
    "atenolol": ["Aten", "Tenormin"],
    "metoprolol": ["Betaloc", "Met XL"],
    "nebivolol": ["Nebicard", "Nebula"],
    "hydrochlorothiazide": ["Aquazide", "Esidrex"],
    "furosemide": ["Lasix", "Fruselac"],
    "atorvastatin": ["Atorva", "Lipitor", "Tonact"],
    "rosuvastatin": ["Rozavel", "Crestor", "Rosuvas"],
    "fenofibrate": ["Lipicard", "Fenolip"],
    "pantoprazole": ["Pan", "Pan-D", "Pantocid"],
    "omeprazole": ["Omez", "Ocid"],
    "esomeprazole": ["Neksium", "Esoz"],
    "rabeprazole": ["Razo", "Rablet"],
    "ranitidine": ["Zinetac", "Aciloc"],
    "domperidone": ["Domstal", "Vomistop"],
    "cetirizine": ["Alerid", "Cetzine", "Okacet"],
    "levocetirizine": ["Xyzal", "Levocet"],
    "fexofenadine": ["Allegra", "Fexova"],
    "montelukast": ["Montair", "Montek"],
    "prednisolone": ["Omnacortil", "Wysolone"],
    "methylprednisolone": ["Medrol", "Solu-Medrol"],
    "dexamethasone": ["Decdan", "Dexona"],
    "levothyroxine": ["Thyronorm", "Eltroxin", "Thyrox"],
    "carbimazole": ["Neo-Mercazole"],
    "clopidogrel": ["Clopitab", "Plavix", "Deplatt"],
    "warfarin": ["Warf", "Coumadin"],
    "rivaroxaban": ["Xarelto", "Xeralto"],
    "apixaban": ["Eliquis", "Apigat"],
    "salbutamol": ["Asthalin", "Ventolin"],
    "ipratropium": ["Ipravent", "Atrovent"],
    "budesonide": ["Budecort", "Pulmicort"],
    "fluticasone": ["Flohale", "Flomist"],
    "escitalopram": ["Nexito", "Cipralex"],
    "sertraline": ["Daxid", "Serta"],
    "fluoxetine": ["Fludac", "Flunil"],
    "alprazolam": ["Alprax", "Trika"],
    "clonazepam": ["Rivotril", "Clonafit"],
    "gabapentin": ["Gabantin", "Gabapin"],
    "pregabalin": ["Pregalin", "Pregeb", "Lyrica"],
    "ferrous sulfate": ["Fefol", "Orofer"],
    "cholecalciferol": ["D-Rise", "Uprise-D3", "Tayo 60K"],
    "cyanocobalamin": ["Methylcobal", "Neurobion"],
    "calcium carbonate": ["Shelcal", "CCM"],
    "folic acid": ["Folvite"],
    "fluconazole": ["Forcan", "Zocon"],
    "acyclovir": ["Acivir", "Zovirax"],
    "ondansetron": ["Emeset", "Vomikind"],
    "tizanidine": ["Tizan", "Sirdalud"],
    "tramadol": ["Ultracet", "Contramal"],
    "spironolactone": ["Aldactone"],
    "etoricoxib": ["Nucoxia", "Arcoxia"],
    "pioglitazone": ["Pioz", "Piozone"],
}

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
OPENFDA_BASE = "https://api.fda.gov/drug/label.json"

# Rate-limit: RxNorm is generous but let's be polite
DELAY_RXNORM = 0.15   # seconds between calls
DELAY_OPENFDA = 0.25


def _get_json(url: str, delay: float = 0.15) -> Optional[Dict]:
    """GET JSON from URL with retry + delay."""
    for attempt in range(3):
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(delay)
            return data
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            log.warning("Attempt %d failed for %s: %s", attempt + 1, url, exc)
            time.sleep(1.5 * (attempt + 1))
    return None


def fetch_class_members(atc_id: str) -> List[Dict[str, str]]:
    """Return list of {rxcui, name} for drugs in an ATC class."""
    url = f"{RXNORM_BASE}/rxclass/classMembers.json?classId={atc_id}&relaSource=ATC"
    data = _get_json(url, DELAY_RXNORM)
    if not data:
        return []
    members = (
        data.get("drugMemberGroup", {}).get("drugMember", [])
    )
    return [
        {"rxcui": m["minConcept"]["rxcui"], "name": m["minConcept"]["name"]}
        for m in members
        if "minConcept" in m
    ]


def fetch_drug_brands(rxcui: str) -> List[str]:
    """Fetch US brand names for an rxcui via RxNorm."""
    url = f"{RXNORM_BASE}/rxcui/{rxcui}/related.json?tty=BN"
    data = _get_json(url, DELAY_RXNORM)
    if not data:
        return []
    groups = data.get("relatedGroup", {}).get("conceptGroup", [])
    brands = []
    for g in groups:
        for prop in g.get("conceptProperties", []):
            brands.append(prop["name"])
    return brands


def fetch_openfda_indication(generic_name: str) -> Optional[str]:
    """Return first-line indication string from OpenFDA, or None."""
    encoded = quote(f'"{generic_name}"')
    url = f"{OPENFDA_BASE}?search=openfda.generic_name:{encoded}&limit=1"
    data = _get_json(url, DELAY_OPENFDA)
    if not data or "results" not in data:
        return None
    results = data["results"]
    if not results:
        return None
    indication = results[0].get("indications_and_usage", [None])[0]
    if indication and len(indication) > 300:
        # Truncate to first sentence
        dot = indication.find(".", 40)
        if dot > 0:
            indication = indication[: dot + 1]
    return indication


def build_medicine_entry(
    generic: str,
    category: str,
    brands_us: List[str],
    indication: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a single medicines.json entry."""
    key = generic.lower().replace(" ", "_").replace("/", "_")
    display = generic.title()
    aliases: List[str] = []
    # Add Indian brands
    indian = INDIAN_BRANDS.get(generic.lower(), [])
    aliases.extend(indian)
    # Add US brands (dedup with Indian)
    seen = {b.lower() for b in aliases}
    for b in brands_us:
        if b.lower() not in seen:
            aliases.append(b)
            seen.add(b.lower())
    # Add lowercase generic as alias
    if generic.lower() not in seen:
        aliases.append(generic.lower())

    entry: Dict[str, Any] = {
        "display_name": display,
        "category": category,
        "aliases": aliases,
    }
    if indication:
        entry["purpose"] = indication

    return key, entry


def run_ingestion(
    class_filter: Optional[Set[str]] = None,
    enrich: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Main ingestion loop. Returns the full medicines dict."""
    medicines: Dict[str, Any] = {}
    total_drugs = 0
    skipped_dupes = 0

    classes_to_process = ATC_CLASSES
    if class_filter:
        classes_to_process = {
            k: v for k, v in ATC_CLASSES.items()
            if v["category"] in class_filter
        }

    log.info("Processing %d ATC classes...", len(classes_to_process))

    for atc_id, meta in classes_to_process.items():
        category = meta["category"]
        label = meta["label"]
        log.info("  [%s] %s (%s)", atc_id, label, category)

        members = fetch_class_members(atc_id)
        log.info("    → %d drugs", len(members))

        for drug in members:
            generic = drug["name"].lower()
            key = generic.replace(" ", "_").replace("/", "_")

            if key in medicines:
                skipped_dupes += 1
                continue

            # Fetch US brand names
            brands = fetch_drug_brands(drug["rxcui"])

            # Optionally enrich with OpenFDA indication
            indication = None
            if enrich:
                indication = fetch_openfda_indication(generic)

            key, entry = build_medicine_entry(generic, category, brands, indication)
            medicines[key] = entry
            total_drugs += 1

    log.info(
        "Done: %d unique drugs ingested, %d duplicates skipped.",
        total_drugs,
        skipped_dupes,
    )

    if not dry_run:
        out_path = CATALOG_DIR / "medicines.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(medicines, f, indent=2, ensure_ascii=False)
        log.info("Wrote %s (%d entries)", out_path, len(medicines))

        # Also generate synonyms additions
        _generate_synonym_additions(medicines)
    else:
        log.info("[DRY-RUN] Would write %d entries", len(medicines))
        # Print sample
        for k, v in list(medicines.items())[:5]:
            log.info("  %s: %s", k, json.dumps(v, ensure_ascii=False)[:120])

    return medicines


def _generate_synonym_additions(medicines: Dict[str, Any]) -> None:
    """Merge medicine aliases into synonyms.json."""
    syn_path = CATALOG_DIR / "synonyms.json"
    synonyms: Dict[str, str] = {}
    if syn_path.exists():
        with open(syn_path, "r") as f:
            synonyms = json.load(f)

    added = 0
    for med_key, meta in medicines.items():
        for alias in meta.get("aliases", []):
            alias_lower = alias.lower().strip()
            if alias_lower and alias_lower not in synonyms:
                synonyms[alias_lower] = med_key
                added += 1

    with open(syn_path, "w", encoding="utf-8") as f:
        json.dump(synonyms, f, indent=2, ensure_ascii=False, sort_keys=True)
    log.info("Updated synonyms.json: +%d medicine aliases", added)


def main():
    parser = argparse.ArgumentParser(description="Ingest drugs from RxNorm → medicines.json")
    parser.add_argument(
        "--classes",
        nargs="+",
        help="Only ingest these category names (e.g. antibiotic analgesic statin)",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Also pull indications from OpenFDA (slower)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview output without writing files",
    )
    args = parser.parse_args()

    class_filter = set(args.classes) if args.classes else None
    run_ingestion(class_filter=class_filter, enrich=args.enrich, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
