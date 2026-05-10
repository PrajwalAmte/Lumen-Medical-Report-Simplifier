"""
PubMed India abstracts collector.

Uses NCBI E-utilities REST API (free, no library required).
With a free NCBI API key (register at ncbi.nlm.nih.gov/account/) rate limit
increases from 3 req/sec to 10 req/sec — register for faster collection.

Output per record:
    {"text": "Title: ...\n\nAbstract: ...", "source": "pubmed", "pmid": "..."}
"""

import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .utils import append_jsonl

ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Targeted queries for Indian medical context relevant to Lumen's use case.
# Each returns up to max_per_query results — queries are intentionally overlapping
# so the deduplication step in collect_all.py handles duplicates.
SEARCH_QUERIES = [
    # Lab tests and diagnostics
    "India[Affiliation] AND (complete blood count OR haemoglobin OR CBC OR haematology)",
    "India[Affiliation] AND (liver function test OR LFT OR SGPT OR SGOT OR bilirubin)",
    "India[Affiliation] AND (kidney function OR creatinine OR urea OR GFR OR nephropathy)",
    "India[Affiliation] AND (lipid profile OR cholesterol OR triglycerides OR LDL OR HDL)",
    "India[Affiliation] AND (thyroid OR TSH OR T3 OR T4 OR hypothyroidism OR hyperthyroidism)",
    "India[Affiliation] AND (HbA1c OR fasting glucose OR diabetes mellitus OR insulin resistance)",
    "India[Affiliation] AND (urine routine OR urinalysis OR microscopy)",
    # Indian high-burden diseases
    "India[Affiliation] AND (tuberculosis OR TB OR pulmonary tuberculosis OR MDR-TB)",
    "India[Affiliation] AND (malaria OR Plasmodium OR dengue fever OR typhoid fever)",
    "India[Affiliation] AND (hypertension OR blood pressure OR cardiovascular disease)",
    "India[Affiliation] AND (iron deficiency anaemia OR thalassaemia OR sickle cell)",
    "India[Affiliation] AND (vitamin D deficiency OR calcium OR osteoporosis)",
    "India[Affiliation] AND (chronic kidney disease OR CKD OR dialysis)",
    "India[Affiliation] AND (fatty liver OR NAFLD OR cirrhosis OR hepatitis B OR hepatitis C)",
    # Pharmacology and Indian drugs
    "India[Affiliation] AND (generic medicine OR Jan Aushadhi OR essential medicine)",
    "India[Affiliation] AND (metformin OR atorvastatin OR amlodipine OR losartan)",
    "India[Affiliation] AND (antibiotic resistance OR fluoroquinolone OR macrolide India)",
    "India[Affiliation] AND (drug interaction OR adverse drug reaction OR pharmacovigilance)",
    # Reference ranges for Indian population
    "Indian population[Title/Abstract] AND (laboratory reference range OR normal values OR reference interval)",
    "India[Affiliation] AND (clinical guidelines OR treatment protocol OR standard of care)",
]


def _fetch_pmids(query: str, max_results: int, api_key: str | None) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": min(max_results, 9999),
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key
    resp = requests.get(f"{ENTREZ_BASE}/esearch.fcgi", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("esearchresult", {}).get("idlist", [])


def _fetch_abstracts_batch(pmids: list[str], api_key: str | None) -> list[dict]:
    """Fetch abstract XML for up to 200 PMIDs at once. Returns list of text dicts."""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    resp = requests.get(f"{ENTREZ_BASE}/efetch.fcgi", params=params, timeout=60)
    resp.raise_for_status()

    records = []
    root = ET.fromstring(resp.content)

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        title_el = article.find(".//ArticleTitle")

        pmid = pmid_el.text if pmid_el is not None else ""
        title = "".join(title_el.itertext()) if title_el is not None else ""

        # Structured abstracts have multiple AbstractText elements with Label attrs
        abstract_parts = []
        for ab_el in article.findall(".//AbstractText"):
            label = ab_el.get("Label", "")
            text = "".join(ab_el.itertext()).strip()
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)

        abstract = " ".join(abstract_parts).strip()
        if abstract:
            records.append({
                "text": f"Title: {title}\n\nAbstract: {abstract}".strip(),
                "source": "pubmed",
                "pmid": pmid,
            })

    return records


def collect(output_path: Path, max_per_query: int = 3000, api_key: str | None = None) -> int:
    """
    Run all search queries and write results to output_path JSONL.

    Args:
        output_path:    Path to write JSONL output.
        max_per_query:  Max PMIDs to fetch per search query (default 3000).
        api_key:        NCBI API key (optional, increases rate limit to 10 req/sec).

    Returns:
        Total number of abstract records written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seen_pmids: set[str] = set()
    total = 0

    # Polite delay between requests
    delay = 0.12 if api_key else 0.35  # 10/sec with key, ~3/sec without

    for q_idx, query in enumerate(SEARCH_QUERIES, 1):
        print(f"  [{q_idx}/{len(SEARCH_QUERIES)}] {query[:70]}...")
        try:
            pmids = _fetch_pmids(query, max_per_query, api_key)
            new_pmids = [p for p in pmids if p not in seen_pmids]
            seen_pmids.update(new_pmids)
            print(f"    Found {len(pmids)} PMIDs, {len(new_pmids)} new")

            # Fetch in batches of 200 (E-utilities limit)
            for batch_start in range(0, len(new_pmids), 200):
                batch = new_pmids[batch_start:batch_start + 200]
                try:
                    records = _fetch_abstracts_batch(batch, api_key)
                    if records:
                        append_jsonl(output_path, records)
                        total += len(records)
                    time.sleep(delay)
                except requests.HTTPError as e:
                    print(f"    Batch HTTP error: {e} — skipping")
                    time.sleep(2)
                except ET.ParseError as e:
                    print(f"    XML parse error: {e} — skipping batch")

        except requests.HTTPError as e:
            print(f"  Search HTTP error: {e} — skipping query")
            time.sleep(5)
        except Exception as e:
            print(f"  Unexpected error on query {q_idx}: {e} — continuing")

    return total
