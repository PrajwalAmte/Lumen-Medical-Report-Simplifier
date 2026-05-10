#!/usr/bin/env python3
"""
Lumen Training Data Collection Orchestrator
============================================

Collects Indian medical domain text for DAPT (domain-adaptive pre-training)
and SFT (supervised fine-tuning) pairs for fine-tuning OpenBioLLM-8B for Lumen.

Usage examples:
    # Run everything (recommended first run):
    python collect_all.py --all --openai-key sk-...

    # Only PubMed abstracts (no API key needed):
    python collect_all.py --pubmed

    # Only drug data (no API key needed):
    python collect_all.py --drugs

    # Only synthetic reports (needs Groq key — free):
    python collect_all.py --synthetic --count 300 --groq-key gsk_...

    # Only synthetic reports (needs OpenAI key — paid):
    python collect_all.py --synthetic --count 300 --openai-key sk-...

    # Only synthetic DAPT text, skip SFT pairs (cheaper):
    python collect_all.py --synthetic --count 500 --openai-key sk-... --no-sft

    # Merge and deduplicate all raw files into final corpus:
    python collect_all.py --deduplicate

    # With NCBI API key for faster PubMed (free at ncbi.nlm.nih.gov/account/):
    python collect_all.py --pubmed --ncbi-key YOUR_NCBI_KEY

Output:
    training/data/raw/           — raw per-source JSONL files
    training/data/processed/
        dapt_corpus.jsonl        — merged & deduplicated DAPT text corpus
        sft_pairs.jsonl          — SFT (instruction, input, output) pairs
"""

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

# Ensure the training/ directory is on the path so collectors can be imported
TRAINING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TRAINING_DIR))

from collectors import drugs, pubmed, synthetic
from collectors.utils import append_jsonl, count_jsonl

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------
DATA_DIR = TRAINING_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

PUBMED_PATH          = RAW_DIR / "pubmed.jsonl"
DRUGS_PATH           = RAW_DIR / "drugs.jsonl"
SYNTHETIC_DAPT_PATH  = RAW_DIR / "synthetic_reports.jsonl"
SYNTHETIC_SFT_PATH   = RAW_DIR / "synthetic_sft_pairs.jsonl"
MINED_DAPT_PATH      = RAW_DIR / "sft_mined_dapt.jsonl"   # DAPT text extracted from old SFT pairs
DAPT_CORPUS_PATH     = PROCESSED_DIR / "dapt_corpus.jsonl"
SFT_CORPUS_PATH      = PROCESSED_DIR / "sft_pairs.jsonl"

# ---------------------------------------------------------------------------
# Lumen system prompt extraction
# Reads directly from the repo's prompts.py so the prompt stays in sync.
# Uses ast.literal_eval (safe — evaluates only Python literals, no code).
# ---------------------------------------------------------------------------

def _load_lumen_system_prompt() -> str:
    """
    Extract Lumen's SYSTEM_PROMPT from backend/app/services/llm_providers/prompts.py.
    Returns the fully assembled prompt string (template + embedded JSON schema).
    Falls back to a minimal prompt if extraction fails.
    """
    prompts_path = (
        TRAINING_DIR.parent
        / "backend"
        / "app"
        / "services"
        / "llm_providers"
        / "prompts.py"
    )
    if not prompts_path.exists():
        print("  WARNING: prompts.py not found — using minimal fallback prompt")
        return _FALLBACK_SYSTEM_PROMPT

    source = prompts_path.read_text(encoding="utf-8")

    # Extract SYSTEM_PROMPT_TEMPLATE string (triple-quoted)
    template_match = re.search(
        r'SYSTEM_PROMPT_TEMPLATE\s*=\s*"""(.*?)"""', source, re.DOTALL
    )
    if not template_match:
        print("  WARNING: SYSTEM_PROMPT_TEMPLATE not found — using fallback prompt")
        return _FALLBACK_SYSTEM_PROMPT
    template = template_match.group(1)

    # Extract _SCHEMA_OBJ dict literal — find balanced braces starting after "_SCHEMA_OBJ = {"
    schema_match = re.search(r"_SCHEMA_OBJ\s*=\s*(\{)", source)
    if not schema_match:
        print("  WARNING: _SCHEMA_OBJ not found — embedding schema as empty dict")
        return template.replace("{{SCHEMA}}", "{}")

    start = schema_match.start(1)
    depth = 0
    end = start
    for i, ch in enumerate(source[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    try:
        # ast.literal_eval is safe — only evaluates Python literal data structures
        schema_obj = ast.literal_eval(source[start:end])
        prompt = template.replace("{{SCHEMA}}", json.dumps(schema_obj, separators=(",", ":")))
        print("  Loaded Lumen system prompt from prompts.py")
        return prompt
    except (ValueError, SyntaxError) as e:
        print(f"  WARNING: schema parse failed ({e}) — using fallback prompt")
        return _FALLBACK_SYSTEM_PROMPT


# Minimal fallback used only if prompts.py is not reachable
_FALLBACK_SYSTEM_PROMPT = (
    "You are Lumen, a medical report explainer for Indian patients. "
    "Output ONLY valid JSON. Extract all test results and medicines. "
    "Use simple Indian English. Never invent medical facts."
)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate_and_merge(input_paths: list[Path], output_path: Path) -> int:
    """
    Merge multiple JSONL files, remove near-duplicates by SHA-256 fingerprint
    of first 512 characters of the text field, write to output_path.

    Returns total unique records written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    total = 0

    print(f"\n  Merging into {output_path.name}...")
    with open(output_path, "w", encoding="utf-8") as out_f:
        for path in input_paths:
            if not path.exists():
                continue
            path_unique = 0
            with open(path, "r", encoding="utf-8") as in_f:
                for line in in_f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        text = record.get("text", "")
                        fingerprint = hashlib.sha256(
                            text[:512].lower().encode()
                        ).hexdigest()
                        if fingerprint not in seen:
                            seen.add(fingerprint)
                            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                            path_unique += 1
                            total += 1
                    except json.JSONDecodeError:
                        continue
            print(f"    {path.name}: {path_unique} unique records kept")

    return total


def migrate_sft_to_dapt() -> int:
    """
    Mine old-format SFT pairs (OCR-text → Lumen-JSON) for reuse as DAPT text.

    Reads each record from SYNTHETIC_SFT_PATH, extracts the assistant turn content
    (the Lumen explanation JSON string), and appends it as a DAPT text record to
    MINED_DAPT_PATH.  Records tagged sft_format=explainer_v2 are already the new
    format and are skipped — they belong in SFT training, not DAPT.

    Returns the number of records successfully migrated.
    """
    if not SYNTHETIC_SFT_PATH.exists():
        print("  No synthetic_sft_pairs.jsonl found — nothing to migrate.")
        return 0

    MINED_DAPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    skipped = 0

    with open(SYNTHETIC_SFT_PATH, encoding="utf-8") as in_f, \
         open(MINED_DAPT_PATH, "a", encoding="utf-8") as out_f:
        for line in in_f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # Skip new-format pairs — they are the correct explainer training data
                if record.get("sft_format") == "explainer_v2":
                    skipped += 1
                    continue
                convs = record.get("conversations", [])
                assistant = next(
                    (c for c in convs if c.get("role") == "assistant"), None
                )
                if not assistant or not assistant.get("content", "").strip():
                    skipped += 1
                    continue
                out_f.write(json.dumps({
                    "text": assistant["content"],
                    "source": "sft_mined_dapt",
                    "profile": record.get("profile", {}),
                }, ensure_ascii=False) + "\n")
                count += 1
            except json.JSONDecodeError:
                skipped += 1

    if skipped:
        print(f"  Skipped  : {skipped} (new explainer format or invalid)")
    return count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lumen training data collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--all", action="store_true",
                        help="Run all collectors then deduplicate")
    parser.add_argument("--pubmed", action="store_true",
                        help="Collect PubMed India abstracts")
    parser.add_argument("--drugs", action="store_true",
                        help="Collect drug data (Jan Aushadhi + OpenFDA)")
    parser.add_argument("--synthetic", action="store_true",
                        help="Generate synthetic Indian lab reports")
    parser.add_argument("--deduplicate", action="store_true",
                        help="Merge and deduplicate all raw JSONL into final corpus")
    parser.add_argument("--count", type=int, default=300,
                        help="Number of synthetic reports to generate (default: 300)")
    parser.add_argument("--openai-key", type=str, default=None,
                        help="OpenAI API key (paid; alternative to --groq-key)")
    parser.add_argument("--groq-key", type=str, default=None,
                        help="Groq API key (free tier; preferred over --openai-key). "
                             "Get one at console.groq.com")
    parser.add_argument("--ncbi-key", type=str, default=None,
                        help="NCBI API key (optional, increases PubMed rate limit)")
    parser.add_argument("--no-sft", action="store_true",
                        help="Skip SFT pair generation in --synthetic mode (cheaper)")
    parser.add_argument("--pubmed-max", type=int, default=3000,
                        help="Max PubMed results per query (default: 3000)")
    parser.add_argument("--migrate-sft", action="store_true",
                        help="Extract old SFT pairs (OCR→JSON format) as DAPT text into "
                             "raw/sft_mined_dapt.jsonl")
    parser.add_argument("--regenerate-sft", action="store_true",
                        help="Migrate old SFT pairs then regenerate in explainer format. "
                             "Use with --count (recommended: 600–800).")

    args = parser.parse_args()

    if not any([args.all, args.pubmed, args.drugs, args.synthetic, args.deduplicate,
                args.migrate_sft, args.regenerate_sft]):
        parser.print_help()
        sys.exit(0)

    run_pubmed    = args.all or args.pubmed
    run_drugs     = args.all or args.drugs
    run_synthetic = args.all or args.synthetic or args.regenerate_sft
    run_dedup     = args.all or args.deduplicate
    run_migrate   = args.migrate_sft or args.regenerate_sft

    print("=" * 65)
    print("  Lumen Training Data Collector")
    print("=" * 65)

    step = 1

    # ------------------------------------------------------------------
    # 0. Migrate old SFT pairs to DAPT (runs before everything else)
    # ------------------------------------------------------------------
    if run_migrate:
        print(f"\n[{step}] Migrate old SFT pairs to DAPT corpus")
        step += 1
        migrated = migrate_sft_to_dapt()
        print(f"  Migrated : {migrated} records → {MINED_DAPT_PATH.name}")
        if args.regenerate_sft and SYNTHETIC_SFT_PATH.exists():
            SYNTHETIC_SFT_PATH.unlink()
            print(f"  Cleared  : {SYNTHETIC_SFT_PATH.name} — will regenerate in explainer format.")

    # ------------------------------------------------------------------
    # 1. PubMed
    # ------------------------------------------------------------------
    if run_pubmed:
        print(f"\n[{step}] PubMed India Medical Abstracts")
        step += 1
        existing = count_jsonl(PUBMED_PATH)
        if existing > 0:
            print(f"  Already collected: {existing:,} records in {PUBMED_PATH.name}")
            print("  Delete the file to re-collect from scratch.")
        else:
            total = pubmed.collect(
                output_path=PUBMED_PATH,
                max_per_query=args.pubmed_max,
                api_key=args.ncbi_key,
            )
            print(f"  Done: {total:,} abstracts → {PUBMED_PATH}")

    # ------------------------------------------------------------------
    # 2. Drug data
    # ------------------------------------------------------------------
    if run_drugs:
        print(f"\n[{step}] Indian Drug Data (Jan Aushadhi + OpenFDA)")
        step += 1
        # Drug data is fast and idempotent — always re-run (overwrites)
        DRUGS_PATH.unlink(missing_ok=True)
        total = drugs.collect(output_path=DRUGS_PATH)
        print(f"  Done: {total} drug records → {DRUGS_PATH}")

    # ------------------------------------------------------------------
    # 3. Synthetic reports
    # ------------------------------------------------------------------
    if run_synthetic:
        print(f"\n[{step}] Synthetic Indian Lab Reports (count={args.count})")
        step += 1

        # Resolve API key and provider — Groq takes priority (it's free)
        if args.groq_key:
            api_key  = args.groq_key
            provider = "groq"
        elif args.openai_key:
            api_key  = args.openai_key
            provider = "openai"
        else:
            print("  ERROR: --groq-key or --openai-key is required for synthetic generation.")
            print("         Groq is free: get a key at console.groq.com")
            sys.exit(1)

        existing_dapt = count_jsonl(SYNTHETIC_DAPT_PATH)
        if existing_dapt > 0:
            print(
                f"  Note: {existing_dapt} DAPT records already exist in "
                f"{SYNTHETIC_DAPT_PATH.name} — new records will be APPENDED."
            )

        # SFT pairs use the explainer format (structured validated input → explanation JSON).
        # The explainer system prompt is defined in collectors/synthetic.py — no external load.
        dapt_count, sft_count = synthetic.collect(
            dapt_output=SYNTHETIC_DAPT_PATH,
            sft_output=SYNTHETIC_SFT_PATH,
            count=args.count,
            api_key=api_key,
            provider=provider,
            generate_sft=not args.no_sft,
        )
        print(f"  Done: {dapt_count} DAPT texts → {SYNTHETIC_DAPT_PATH}")
        if not args.no_sft:
            print(f"        {sft_count} SFT pairs  → {SYNTHETIC_SFT_PATH}")

    # ------------------------------------------------------------------
    # 4. Deduplicate and assemble final corpus
    # ------------------------------------------------------------------
    if run_dedup:
        print(f"\n[{step}] Deduplication and Corpus Assembly")
        step += 1

        # DAPT corpus — merge all text sources including mined SFT assistant responses
        dapt_sources = [PUBMED_PATH, DRUGS_PATH, SYNTHETIC_DAPT_PATH, MINED_DAPT_PATH]
        total_dapt = _deduplicate_and_merge(dapt_sources, DAPT_CORPUS_PATH)
        print(f"  DAPT corpus: {total_dapt:,} unique records → {DAPT_CORPUS_PATH}")

        # SFT pairs — copy with basic validation (no dedup needed at this scale)
        if SYNTHETIC_SFT_PATH.exists():
            valid_sft = 0
            invalid_sft = 0
            SFT_CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(SYNTHETIC_SFT_PATH, "r") as in_f, \
                 open(SFT_CORPUS_PATH, "w") as out_f:
                for line in in_f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        # Must have conversations with at least system + user + assistant
                        convs = record.get("conversations", [])
                        if len(convs) >= 3:
                            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                            valid_sft += 1
                        else:
                            invalid_sft += 1
                    except json.JSONDecodeError:
                        invalid_sft += 1
            print(f"  SFT pairs: {valid_sft} valid → {SFT_CORPUS_PATH}")
            if invalid_sft:
                print(f"            {invalid_sft} invalid records dropped")
        else:
            print("  SFT pairs: no synthetic_sft_pairs.jsonl found — run --synthetic first")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 65)
    print("  Collection complete.")
    print()

    for label, path in [
        ("DAPT corpus  ", DAPT_CORPUS_PATH),
        ("SFT pairs    ", SFT_CORPUS_PATH),
        ("PubMed raw   ", PUBMED_PATH),
        ("Drug raw     ", DRUGS_PATH),
        ("Synthetic raw", SYNTHETIC_DAPT_PATH),
        ("SFT mined    ", MINED_DAPT_PATH),
    ]:
        if path.exists():
            size_mb = path.stat().st_size / (1024 * 1024)
            count = count_jsonl(path)
            print(f"  {label}  {path.name:<35} {count:>7,} records  {size_mb:.1f} MB")

    print()
    print("  Next steps:")
    print("  1. Upload dapt_corpus.jsonl to Kaggle dataset or Google Drive")
    print("  2. Run Phase 1 DAPT notebook on Kaggle (OpenBioLLM-8B + Unsloth)")
    print("  3. Run Phase 2 SFT notebook with sft_pairs.jsonl")
    print("  4. Push merged model to HuggingFace Hub private repo")
    print("  5. Test locally with Ollama before swapping provider in Lumen")
    print("=" * 65)


if __name__ == "__main__":
    main()
