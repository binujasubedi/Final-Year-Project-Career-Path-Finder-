# src/parsing/resume_parser.py
import unicodedata
from pathlib import Path
from typing import Dict, List

from .docx_parser import extract_text_from_docx
from .pdf_parser_improved import extract_text_from_pdf
from .text_cleaner import clean_and_preserve_structure
from .enhanced_parser import enhanced_extract_sections


def normalize_text(text: str) -> str:
    """
    Normalize PDF/OCR text: remove control characters, weird unicode, and extra spaces.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\xa0", " ").replace("\t", " ").replace("\r", " ")
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    return text.strip()


def extract_sections(text: str) -> Dict[str, List[str]]:
    """
    Extract structured fields from resume text using the shared enhanced parser.
    """
    if not text:
        return {"skills": [], "education": [], "experience": []}

    text = normalize_text(text)
    text = clean_and_preserve_structure(text)
    return enhanced_extract_sections(text)


def parse_resume(file_path: str) -> Dict[str, List[str]]:
    """
    Wrapper function to parse a resume file.
    Reads file, extracts text, and returns structured sections.
    """
    try:
        path = Path(file_path)
        if path.suffix.lower() == ".pdf":
            raw_text = extract_text_from_pdf(file_path)
        elif path.suffix.lower() == ".docx":
            raw_text = extract_text_from_docx(file_path)
        else:
            raw_text = path.read_text(encoding="utf-8")

        if not raw_text:
            return {"skills": [], "education": [], "experience": []}

        return extract_sections(raw_text)

    except Exception as e:
        print(f"⚠️ Failed to parse resume {file_path}: {e}")
        return {"skills": [], "education": [], "experience": []}
