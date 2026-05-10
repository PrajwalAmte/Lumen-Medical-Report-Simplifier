"""
Intermediate representation for the extraction pipeline.

Every extraction path (digital text, PaddleOCR, Vision LLM) produces
these dataclasses.  Downstream validation, normalization, and the LLM
explanation layer all consume this single contract — never raw strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PageContent:
    """A single page from a document with line-level structure preserved."""

    page_num: int       # 1-indexed
    lines: List[str]    # each non-empty line as a separate string
    raw_text: str       # full page text (joined lines) — kept for LLM context
    # Set by document_classifier.detect_sections on the extracted text.
    # Values: "ecg", "echo", "radiology", "general".  Empty = lab table / unknown.
    detected_sections: List[str] = field(default_factory=list)


@dataclass
class ExtractedValue:
    """A single lab test value with full extraction provenance."""

    test_id: str                    # catalog key: "hba1c", "potassium", …
    raw_name: str                   # name exactly as found: "Glycated Haemoglobin"
    raw_value: str                  # numeric string exactly as found: "5.9", "46.7"
    value_numeric: Optional[float]  # parsed float — None if unparseable
    unit: str                       # normalized unit: "%", "mEq/L"
    ref_range_raw: str              # reference range as printed: "4.0–5.6"
    ref_min: Optional[float]
    ref_max: Optional[float]
    source_page: int                # 1-indexed page where value was found
    source_line: str                # exact text line it was extracted from
    extraction_tier: str            # "digital_text" | "paddle_table" | "vlm"

    # Set by medical_validator.validate() — never pre-set by extractors
    validator_status: str = "pending"  # "pending" | "passed" | "flagged" | "rejected"
    validator_note: str = ""           # human-readable reason for flag/rejection

    # Set by medical_validator.validate() after status is determined
    confidence: float = 0.0            # 0.0–1.0


@dataclass
class ExtractedMedicine:
    """A single medicine reference found in the document."""

    id: str
    name: str
    category: Optional[str]
    source_page: int
    source_line: str


@dataclass
class ExtractionResult:
    """Complete output of one extraction pass over a document."""

    values: List[ExtractedValue] = field(default_factory=list)
    medicines: List[ExtractedMedicine] = field(default_factory=list)
    pages: List[PageContent] = field(default_factory=list)
    extraction_tier: str = "digital_text"
