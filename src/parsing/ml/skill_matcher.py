# src/ml/skill_matcher.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import re
import pandas as pd

# Import parse_resume safely
try:
    from src.parsing import parse_resume
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.parsing import parse_resume

# ----------------------------
# Paths
# ----------------------------
PROJ_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJ_ROOT / "models"
DATASET_CSV = MODELS_DIR / "skills_dataset.csv"

# ----------------------------
# Default Skill Synonyms
# ----------------------------
SKILL_SYNONYMS = {
    "python": ["python", "py", "python3", "python programming"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "data visualization": ["data visualization", "visualization", "matplotlib", "seaborn", "plotly"],
    "sql": ["sql", "mysql", "postgresql"],
    "statistics": ["statistics", "stats", "statistical analysis"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "eda": ["eda", "exploratory data analysis"],
    "communication": ["communication", "communication skills", "verbal communication"],
    "machine learning": ["machine learning", "ml", "statistical learning"],
    "deep learning": ["deep learning", "dl", "neural networks"],
    "tensorflow": ["tensorflow", "tf"],
    "pytorch": ["pytorch", "torch"],
    "docker": ["docker", "containerization"],
    "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services", "amazon aws"],
    "azure": ["azure", "microsoft azure"],
    "git": ["git", "github", "gitlab", "version control"],
    "rest api": ["rest", "rest api", "restful", "api"],
    "agile": ["agile", "scrum", "agile methodology"],
    # Add more as needed
}

# ----------------------------
# Skill Normalization
# ----------------------------
def normalize_skill_to_base(skill: str) -> str:
    """Normalize skill to its base form using SKILL_SYNONYMS."""
    if not skill:
        return ""
    skill_lower = re.sub(r'[^\w\s]', '', skill.lower().strip())
    skill_lower = re.sub(r'\s+', ' ', skill_lower)
    for base, synonyms in SKILL_SYNONYMS.items():
        if skill_lower == base or skill_lower in synonyms:
            return base
    return skill_lower

# ----------------------------
# Debugging Helper
# ----------------------------
def debug_skill_matching(resume_skills: List[str], required_skills: List[str]):
    """Optional debug function to visualize skill matching."""
    normalized_resume = [normalize_skill_to_base(s) for s in resume_skills]
    normalized_required = [normalize_skill_to_base(s) for s in required_skills]
    matched = set(normalized_resume) & set(normalized_required)
    missing = set(normalized_required) - set(normalized_resume)
    print("=== DEBUG SKILL MATCHING ===")
    print(f"Resume: {normalized_resume}")
    print(f"Required: {normalized_required}")
    print(f"Matched: {matched}")
    print(f"Missing: {missing}")
    print("=============================")

# ----------------------------
# Dataset Loaders
# ----------------------------
def load_skill_dataset(csv_path: Path = DATASET_CSV) -> Dict[str, List[str]]:
    """Load job roles and required skills from CSV, fallback to defaults."""
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            roles_map = {}
            for _, row in df.iterrows():
                role = row['role']
                skills = [s.strip() for s in row['skills'].split(';') if s.strip()]
                roles_map[role] = skills
            return roles_map
        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
    # Fallback roles
    return get_fallback_roles()

def get_fallback_roles() -> Dict[str, List[str]]:
    """Comprehensive fallback dataset of roles and skills."""
    return {
        'Junior Data Scientist': ['Python', 'Pandas', 'Numpy', 'Data Visualization', 'SQL', 'Statistics', 'Scikit-learn', 'EDA', 'Communication'],
        'Senior Data Scientist': ['Machine Learning', 'Deep Learning', 'Big Data', 'Cloud', 'NLP', 'Model Deployment', 'Leadership', 'Advanced Statistics'],
        'Junior Data Analyst': ['Excel', 'SQL', 'Python', 'Data Visualization', 'Statistics', 'Reporting'],
        'Senior Data Analyst': ['Advanced SQL', 'Predictive Analytics', 'Business Strategy', 'ETL', 'Data Warehousing', 'Communication'],
        'Data Engineer': ['SQL', 'Python', 'ETL', 'Data Warehousing', 'Apache Spark', 'Big Data'],
        'Software Engineer': ['Python', 'Java', 'Git', 'Algorithms', 'Data Structures', 'OOP'],
        'DevOps Engineer': ['Docker', 'Linux', 'AWS', 'CI/CD', 'Scripting', 'Kubernetes'],
        # Add remaining roles to cover 20+
    }

# ----------------------------
# Resume Parsing
# ----------------------------
def parse_resume_structured(file_path: str) -> Dict[str, List[str]]:
    """Parse resume into structured fields."""
    try:
        result = parse_resume(file_path)
        if not isinstance(result, dict):
            return {"skills": [], "education": [], "experience": []}
        skills = result.get("skills", [])
        if isinstance(skills, str):
            skills = [skills]
        return {
            "skills": skills,
            "education": result.get("education", []),
            "experience": result.get("experience", [])
        }
    except Exception as e:
        print(f"⚠️ parse_resume_structured failed: {e}")
        return {"skills": [], "education": [], "experience": []}

# ----------------------------
# Skill Gap Computation
# ----------------------------
def compute_skill_gap(resume_skills: List[str], required_skills: List[str]) -> Dict[str, List[str]]:
    """Compute matched and missing skills with normalization."""
    normalized_resume = {normalize_skill_to_base(s) for s in resume_skills}
    normalized_required = {normalize_skill_to_base(s) for s in required_skills}
    skill_mapping = {normalize_skill_to_base(s): s for s in required_skills}
    matched = [skill_mapping[s] for s in (normalized_resume & normalized_required)]
    missing = [skill_mapping[s] for s in (normalized_required - normalized_resume)]
    return {"matched": matched, "missing": missing}

# ----------------------------
# End-to-End Resume Analysis
# ----------------------------
def analyze_resume(file_path: str, chosen_role: Optional[str] = None, debug: bool = False) -> Dict:
    """
    Full resume analysis: parses resume, predicts top roles, computes skill gap and match score.
    """
    roles_map = load_skill_dataset()
    structured = parse_resume_structured(file_path)
    skills_list = structured.get("skills", [])

    if debug:
        print(f"DEBUG: Parsed skills: {skills_list}")

    # Predict roles
    predictions = []
    for role, required_skills in roles_map.items():
        gap = compute_skill_gap(skills_list, required_skills)
        match_score = (len(gap["matched"]) / len(required_skills)) * 100 if required_skills else 0
        predictions.append((role, match_score))
    predictions.sort(key=lambda x: x[1], reverse=True)

    if chosen_role is None:
        chosen_role = predictions[0][0] if predictions else next(iter(roles_map.keys()))
    required_skills = roles_map.get(chosen_role, [])
    gap = compute_skill_gap(skills_list, required_skills)
    score = (len(gap["matched"]) / len(required_skills)) * 100 if required_skills else 0.0

    if debug:
        print(f"DEBUG: Required skills for {chosen_role}: {required_skills}")
        debug_skill_matching(skills_list, required_skills)

    return {
        "parsed": structured,
        "predictions": predictions[:3],
        "chosen_role": chosen_role,
        "required_skills": required_skills,
        "gap": gap,
        "match_score": score
    }
