# src/parsing/resume_analysis.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import re
import unicodedata

try:
    from src.parsing import parse_resume_with_text
    from src.database import SkillRepository
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.parsing import parse_resume_with_text
    from src.database import SkillRepository

# ---------- Default Skill Synonyms ----------
SKILL_SYNONYMS = {
    "python": ["python", "py", "python3", "python programming"],
    "javascript": ["javascript", "js", "ecmascript", "es6", "es2015"],
    "java": ["java", "java programming"],
    "pandas": ["pandas", "pd"],
    "numpy": ["numpy", "np"],
    "react": ["react", "reactjs", "react.js"],
    "node.js": ["node", "nodejs", "node.js"],
    "sql": ["sql", "mysql", "postgresql", "postgres", "structured query language"],
    "machine learning": ["machine learning", "ml", "statistical learning"],
    "deep learning": ["deep learning", "dl", "neural networks"],
    "data visualization": ["data visualization", "visualization", "matplotlib", "seaborn", "plotly"],
    "statistics": ["statistics", "stats", "statistical analysis"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "tensorflow": ["tensorflow", "tf"],
    "pytorch": ["pytorch", "torch"],
    "docker": ["docker", "containerization"],
    "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services", "amazon aws"],
    "azure": ["azure", "microsoft azure"],
    "git": ["git", "github", "gitlab", "version control"],
    "rest api": ["rest", "rest api", "restful", "api"],
    "agile": ["agile", "scrum", "agile methodology"],
    "communication": ["communication", "communication skills", "verbal communication"],
}

DEFAULT_ROLE_SKILLS = {
    "Cybersecurity Analyst": [
        "Information Security", "Risk Analysis", "Ethical Hacking", "VAPT",
        "Oracle", "Communication", "SQL"
    ],
    "Information Security Analyst": [
        "Information Security", "Risk Analysis", "VAPT", "Ethical Hacking",
        "Communication", "Oracle", "Git"
    ],
    "Junior Data Scientist": [
        "Python", "Pandas", "Numpy", "Data Visualization",
        "SQL", "Statistics", "Scikit-learn", "EDA", "Communication"
    ],
    "Data Analyst": [
        "SQL", "Excel", "Data Visualization", "Statistics",
        "Reporting", "Communication"
    ],
    "Software Engineer": [
        "Python", "JavaScript", "Git", "SQL",
        "REST API", "Docker", "Communication"
    ],
}

# ---------- Text Normalization ----------
def normalize_text(text: str) -> str:
    """
    Normalize PDF/OCR text: remove control chars, unicode issues, collapse spaces.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\xa0", " ").replace("\t", " ").replace("\r", " ")
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# ---------- Skill Synonyms ----------
def build_skill_synonyms_from_db(skill_repo: SkillRepository) -> Dict[str, List[str]]:
    """
    Merge default skill synonyms with database entries.
    """
    try:
        all_skills = skill_repo.get_all_skills()
        synonyms_map = {}
        for skill in all_skills:
            skill_name = skill['skill_name'].lower()
            synonyms = skill.get('synonyms', [])
            if isinstance(synonyms, list):
                synonyms_map[skill_name] = [s.lower() for s in synonyms]
            else:
                synonyms_map[skill_name] = [skill_name]
        return {**SKILL_SYNONYMS, **synonyms_map}
    except Exception as e:
        print(f"⚠️ Could not load skills from DB: {e}")
        return SKILL_SYNONYMS

# ---------- Skill Normalization ----------
def normalize_skill_to_base(skill: str, synonyms_map: Dict[str, List[str]] = None) -> str:
    """
    Normalize a single skill to its base form using synonyms mapping.
    """
    if not skill:
        return ""
    if synonyms_map is None:
        synonyms_map = SKILL_SYNONYMS

    skill_lower = skill.lower().strip()
    skill_lower = re.sub(r'[^\w\s]', '', skill_lower)
    skill_lower = re.sub(r'\s+', ' ', skill_lower)

    for base, synonyms in synonyms_map.items():
        if skill_lower in synonyms or skill_lower == base:
            return base
    return skill_lower

# ---------- Load Job Roles ----------
def load_skill_dataset_from_db() -> Dict[str, List[str]]:
    """
    Load job roles and required skills from DB (fallback to defaults).
    """
    try:
        skill_repo = SkillRepository()
        roles_map = skill_repo.get_all_job_roles()
        if roles_map:
            return {**DEFAULT_ROLE_SKILLS, **roles_map}
        print("⚠️ No job roles found in DB, using local defaults")
        return DEFAULT_ROLE_SKILLS
    except Exception as e:
        print(f"⚠️ Could not load roles from DB: {e}")
        return DEFAULT_ROLE_SKILLS

# ---------- Resume Parsing ----------
def parse_resume_structured(file_path: str) -> Dict[str, List[str]]:
    """
    Parse resume file into structured fields: skills, education, experience.
    """
    try:
        parsed_resume = parse_resume_with_text(file_path)
        result = parsed_resume.get("structured", {}) if parsed_resume else {}
        if not isinstance(result, dict):
            return {"skills": [], "education": [], "experience": [], "raw_text": ""}

        skills = result.get("skills", [])
        if isinstance(skills, str):
            skills = [skills]

        return {
            "skills": skills,
            "education": result.get("education", []),
            "experience": result.get("experience", []),
            "raw_text": parsed_resume.get("raw_text", "") if parsed_resume else ""
        }
    except Exception as e:
        print(f"⚠️ parse_resume_structured failed: {e}")
        return {"skills": [], "education": [], "experience": [], "raw_text": ""}

# ---------- Skill Gap Computation ----------
def compute_skill_gap(resume_skills: List[str], required_skills: List[str],
                      synonyms_map: Dict[str, List[str]] = None) -> Dict[str, List[str]]:
    """
    Compute matched and missing skills using normalization.
    """
    if synonyms_map is None:
        try:
            skill_repo = SkillRepository()
            synonyms_map = build_skill_synonyms_from_db(skill_repo)
        except:
            synonyms_map = SKILL_SYNONYMS

    normalized_resume = {normalize_skill_to_base(s, synonyms_map) for s in resume_skills}
    normalized_required = {normalize_skill_to_base(s, synonyms_map) for s in required_skills}

    skill_mapping = {normalize_skill_to_base(s, synonyms_map): s for s in required_skills}

    matched = [skill_mapping[s] for s in (normalized_resume & normalized_required)]
    missing = [skill_mapping[s] for s in (normalized_required - normalized_resume)]

    return {"matched": matched, "missing": missing}

# ---------- End-to-End Resume Analysis ----------
def analyze_resume(file_path: str, chosen_role: Optional[str] = None) -> Dict:
    """
    Full resume analysis with predictions, skill gap, match score.
    """
    roles_map = load_skill_dataset_from_db()
    structured = parse_resume_structured(file_path)
    skills_list = structured.get("skills", [])

    print(f"DEBUG: Parsed skills: {skills_list}")

    # Build synonyms map
    try:
        skill_repo = SkillRepository()
        synonyms_map = build_skill_synonyms_from_db(skill_repo)
    except:
        synonyms_map = SKILL_SYNONYMS

    # Compute predictions
    predictions = []
    for role, required_skills in roles_map.items():
        gap = compute_skill_gap(skills_list, required_skills, synonyms_map)
        match_score = (len(gap["matched"]) / len(required_skills)) * 100 if required_skills else 0
        predictions.append((role, match_score))
    predictions.sort(key=lambda x: x[1], reverse=True)

    if chosen_role is None:
        chosen_role = predictions[0][0] if predictions else next(iter(roles_map.keys()))
    required_skills = roles_map.get(chosen_role, [])
    gap = compute_skill_gap(skills_list, required_skills, synonyms_map)
    score = (len(gap["matched"]) / len(required_skills)) * 100 if required_skills else 0.0

    return {
        "parsed": structured,
        "predictions": predictions[:3],
        "chosen_role": chosen_role,
        "required_skills": required_skills,
        "gap": gap,
        "match_score": score
    }
