# src/parsing/resume_parser.py
import re
import unicodedata
from typing import Dict, List


def normalize_text(text: str) -> str:
    """
    Normalize PDF/OCR text: remove control characters, weird unicode, and extra spaces.
    """
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    # Replace non-breaking spaces, tabs, carriage returns
    text = text.replace("\xa0", " ").replace("\t", " ").replace("\r", " ")
    # Remove other control characters
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    # Collapse multiple spaces/newlines into single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def split_skills_by_uppercase(text: str) -> List[str]:
    """
    Split a string of skills by uppercase letters (camelCase splitting)
    Example: "PythonMachineLearningSQL" -> ["Python", "Machine", "Learning", "SQL"]
    """
    skills = re.findall(r'[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)', text)
    return [skill.strip() for skill in skills if skill.strip()]


def extract_sections(text: str) -> Dict[str, List[str]]:
    """
    Extract structured fields from resume text: skills, education, experience.
    """
    text = normalize_text(text)
    text_lower = text.lower()

    sections = {"skills": [], "education": [], "experience": []}

    # --- Extract Skills ---
    skills_patterns = [
        r"(technical\s+skills|skills|technologies|expertise|competencies)[:\-]?\s*(.*?)(?=education|experience|work|$)",
        r"(programming\s+languages|tools|software\s+skills)[:\-]?\s*(.*?)(?=education|experience|work|$)",
    ]
    for pattern in skills_patterns:
        try:
            match = re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL)
        except re.error as e:
            print(f"⚠️ Regex error in skills pattern: {e}")
            continue

        if match and match.group(2):
            skills_text = match.group(2).strip()
            if any(d in skills_text for d in [',', ';', '•', '\n']):
                skills = [s.strip() for s in re.split(r'[,;•\n]', skills_text) if s.strip()]
            else:
                skills = split_skills_by_uppercase(skills_text)
            sections["skills"].extend(skills)
            break

    # --- Extract Education ---
    education_patterns = [
        r"(education|academic\s+background|qualifications|degrees)[:\-]?\s*(.*?)(?=experience|skills|work|$)",
        r"(university|college|school|bachelor|master|phd)[\s\w]*[:\-]?\s*(.*?)(?=experience|skills|work|$)",
    ]
    for pattern in education_patterns:
        try:
            match = re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL)
        except re.error as e:
            print(f"⚠️ Regex error in education pattern: {e}")
            continue

        if match:
            edu_text = (match.group(2) or match.group(1)).strip()
            education = [e.strip() for e in re.split(r'[\n•]', edu_text) if e.strip()]
            sections["education"].extend(education)
            break

    # --- Extract Experience ---
    experience_patterns = [
        r"(experience|work\s+history|employment|professional)[:\-]?\s*(.*?)(?=education|skills|$)",
        r"(internship|work|job|position)[\s\w]*[:\-]?\s*(.*?)(?=education|skills|$)",
    ]
    for pattern in experience_patterns:
        try:
            match = re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL)
        except re.error as e:
            print(f"⚠️ Regex error in experience pattern: {e}")
            continue

        if match:
            exp_text = (match.group(2) or "").strip()
            experience = [e.strip() for e in re.split(r'[\n•]', exp_text) if e.strip()]
            sections["experience"].extend(experience)
            break

    # --- Deduplicate while preserving order ---
    for key in sections:
        seen = set()
        cleaned = []
        for item in sections[key]:
            if item not in seen:
                seen.add(item)
                cleaned.append(item)
        sections[key] = cleaned

    return sections


def parse_resume(file_path: str) -> Dict[str, List[str]]:
    """
    Wrapper function to parse a resume file.
    Reads file, extracts text, and returns structured sections.
    """
    try:
        # Detect file type by extension
        text = ""
        if file_path.lower().endswith(".pdf"):
            from src.parsing import pdf_parser_final as pdf_parser
            text = pdf_parser.extract_text(file_path)
        elif file_path.lower().endswith(".docx"):
            from src.parsing import docx_parser
            text = docx_parser.extract_text(file_path)
        else:
            # Fallback: read as text
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()

        return extract_sections(text)

    except Exception as e:
        print(f"⚠️ Failed to parse resume {file_path}: {e}")
        return {"skills": [], "education": [], "experience": []}
