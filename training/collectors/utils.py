"""Shared utilities for all Lumen training data collectors."""

import json
from pathlib import Path


def append_jsonl(path: Path, records: list[dict]) -> None:
    """Append records to a JSONL file, creating it if it doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def count_jsonl(path: Path) -> int:
    """Count the number of lines (records) in a JSONL file."""
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())
