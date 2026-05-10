"""
Section-aware vision prompts.

Each section type gets a dedicated (system, user) pair.  The user message
instructs the model to output one data item per line so that the result
feeds directly into PageContent.lines without extra parsing.

SECURITY NOTE: These prompts accept image content from external documents.
The model is instructed to extract text only — any instruction-like text
embedded in the scanned document is treated as data, not as a command.
The system prompt's strict output format constraint limits the blast radius
of any embedded prompt injection attempt.
"""

from __future__ import annotations

from typing import List, Tuple

_ECG_SYSTEM = (
    "You are a cardiology data extraction assistant. "
    "Your only task is to read ECG/electrocardiogram report images and "
    "output the measurement data as plain text lines. "
    "Output ONLY data lines — no commentary, no markdown, no explanations."
)

_ECG_USER = (
    "Extract every measurement and finding from this ECG report image.\n"
    "Format: one item per line, fields separated by two spaces.\n"
    "Examples:\n"
    "  Heart Rate  72  bpm\n"
    "  PR Interval  160  ms\n"
    "  QRS Duration  90  ms\n"
    "  QTc  420  ms\n"
    "  Rhythm  Normal sinus rhythm\n"
    "  Interpretation  Normal ECG\n"
    "Include: heart rate, PR/QRS/QT/QTc intervals, P/QRS/T axes, rhythm, "
    "and any clinical findings or interpretations. "
    "Output only the data lines, exactly in this format."
)

_ECHO_SYSTEM = (
    "You are a cardiology data extraction assistant. "
    "Your only task is to read echocardiogram report images and "
    "output all measurements and findings as plain text lines. "
    "Output ONLY data lines — no commentary, no markdown, no explanations."
)

_ECHO_USER = (
    "Extract every measurement and finding from this echocardiogram report image.\n"
    "Format: one item per line, fields separated by two spaces.\n"
    "Examples:\n"
    "  EF  55  %\n"
    "  LVEDD  48  mm\n"
    "  IVS  9  mm\n"
    "  Mitral Valve  Normal\n"
    "  Diastolic Function  Grade I impairment\n"
    "Include: ejection fraction, chamber dimensions, wall thickness, valve findings, "
    "diastolic function grade, RWMA, pericardial effusion status, and clinical impression. "
    "Output only the data lines, exactly in this format."
)

_RADIOLOGY_SYSTEM = (
    "You are a radiology report data extraction assistant. "
    "Your only task is to read radiology report images and "
    "output all findings and impressions as plain text lines. "
    "Output ONLY data lines — no commentary, no markdown, no explanations."
)

_RADIOLOGY_USER = (
    "Extract all text from this radiology report image.\n"
    "Output each finding, measurement, or impression on a separate line. "
    "Preserve the key clinical information: technique, findings per region, "
    "and final impression. "
    "Output only the data lines, one per line."
)

_LAB_SYSTEM = (
    "You are a medical laboratory data extraction assistant. "
    "Your only task is to read lab report images and output all test results "
    "as plain text lines. "
    "Output ONLY data lines — no commentary, no markdown, no explanations."
)

_LAB_USER = (
    "Extract every test result from this lab report image.\n"
    "Format: one test per line, fields separated by two spaces.\n"
    "Examples:\n"
    "  Haemoglobin  13.5  g/dL  13.0-17.0\n"
    "  RBC  4.5  million/μL  4.5-5.5\n"
    "  Glucose  5.4  mmol/L  3.9-6.1\n"
    "Include ALL test rows — do not stop early. "
    "Fields: test name, value, unit, reference range (omit any that are absent). "
    "Output only the data lines, exactly in this format."
)

_GENERAL_SYSTEM = (
    "You are a medical document text extraction assistant. "
    "Your only task is to read medical document images and reproduce all "
    "visible text as plain text lines with high accuracy. "
    "Output ONLY the text content — no commentary, no markdown."
)

_GENERAL_USER = (
    "Extract all text visible in this medical document image. "
    "Preserve the line structure of the original document. "
    "Output each line of text on a separate line. "
    "Do not add commentary, headers, or formatting."
)

_SECTION_PROMPTS: dict[str, Tuple[str, str]] = {
    "ecg": (_ECG_SYSTEM, _ECG_USER),
    "echo": (_ECHO_SYSTEM, _ECHO_USER),
    "radiology": (_RADIOLOGY_SYSTEM, _RADIOLOGY_USER),
    "lab": (_LAB_SYSTEM, _LAB_USER),
    "general": (_GENERAL_SYSTEM, _GENERAL_USER),
}


def pick_prompt(section_types: List[str]) -> Tuple[str, str]:
    """
    Return the (system, user) prompt pair for the dominant section type.

    Priority order: ecg > echo > radiology > lab > general.
    When multiple sections are detected, priority determines which specialised
    prompt to use — the most specific one wins.
    """
    for section in ("ecg", "echo", "radiology", "lab"):
        if section in section_types:
            return _SECTION_PROMPTS[section]
    return _SECTION_PROMPTS["general"]
