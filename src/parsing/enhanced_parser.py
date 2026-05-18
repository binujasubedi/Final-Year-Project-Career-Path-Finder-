import re
from typing import Dict, List
from .text_cleaner import clean_skill_list
from .pdf_table_extractor import extract_skills_from_pdf_tables


SECTION_HEADERS = {
    "skills": [
        "skills/core competencies",
        "core competencies",
        "technical skills",
        "technical",
        "skills",
        "technologies",
        "expertise",
        "competencies",
        "proficiencies",
    ],
    "education": [
        "education",
        "academic background",
        "academic qualifications",
        "academics",
        "qualifications",
        "degrees",
    ],
    "experience": [
        "internships & experience",
        "internships",
        "internship",
        "career history",
        "work experience",
        "professional experience",
        "employment history",
        "employment",
        "experience",
        "teaching/academic experiences",
        "teaching academic experiences",
    ],
    "certifications": [
        "certifications",
        "certification",
        "certificates",
        "licenses",
    ],
    "stop": [
        "summary",
        "profile",
        "objective",
        "projects",
        "project",
        "languages",
        "trainings",
        "training",
        "basic information",
        "personal information",
    ],
}

TEMPLATE_NOISE_PATTERNS = (
    "qwikresume",
    "free resume template",
    "copyright",
    "usage guidelines",
    "guidelines",
)


def _heading_regex(header: str) -> str:
    return r"\s+".join(re.escape(part) for part in header.split())


def detect_section_heading(line: str) -> tuple[str, str] | None:
    """Detect real section headings at the start of a line."""
    clean_line = re.sub(r"^[^\w\d]+", "", line or "").strip()
    if not clean_line:
        return None

    for section, headers in SECTION_HEADERS.items():
        for header in sorted(headers, key=len, reverse=True):
            pattern = rf"^{_heading_regex(header)}\b(?P<rest>.*)$"
            match = re.match(pattern, clean_line, re.IGNORECASE)
            if not match:
                continue

            rest = match.group("rest").strip(" :-–—\t")
            if rest and re.search(r"\w", rest):
                # Reject sentences that start with a section keyword but are not headings.
                continue
            rest = rest.lstrip("&").strip(" :-–—\t")
            return section, rest

    return None


def extract_section_content(text: str, target_section: str) -> str:
    """Capture a section from one heading until the next resume heading."""
    captured: list[str] = []
    capturing = False

    for line in text.splitlines():
        heading = detect_section_heading(line)
        if heading:
            section, rest = heading
            if capturing:
                if section == target_section:
                    if rest:
                        captured.append(rest)
                    continue
                break
            if section == target_section:
                capturing = True
                if rest:
                    captured.append(rest)
            continue

        if capturing:
            captured.append(line)

    return "\n".join(captured).strip()


BULLET_LINE_RE = re.compile(r"^\s*(?:(?:[•▪*–—¢]|(?:\d+[.)]))\s*)+")


def strip_bullet_prefix(item: str) -> str:
    return BULLET_LINE_RE.sub("", item or "").strip()


def clean_resume_item(item: str) -> str:
    """Normalize extracted education/experience text without changing meaning."""
    item = strip_bullet_prefix(item)
    item = re.sub(r"^[\.\s]+", "", item or "").strip()
    item = re.sub(r"^o\s+", "", item, flags=re.IGNORECASE)
    item = re.sub(r"\s+", " ", item)
    item = item.replace(" ,", ",").replace(" .", ".")
    item = re.sub(r"\b[Tt]ill\s+[Nn]ow\b", "Present", item)
    item = re.sub(r"\b[Nn]ow\b\.?$", "Present", item)
    return item.strip(" ;,.")


def is_noise_item(item: str) -> bool:
    item = clean_resume_item(item)
    lower = item.lower()
    blocked_exact = {
        "professional",
        "academic",
        "background",
        "summary",
        "education",
        "experience",
        "career history",
        "skills",
        "data storage",
        "c",
        ", professional",
        "guidelines",
        "usage guidelines",
    }
    blocked_starts = (
        "experiences ",
        "with aggregate",
        "with an aggregate",
        "completed ",
        "training ",
    )

    blocked_short_starts = (
        "background ",
    )

    if any(lower.startswith(prefix) for prefix in blocked_short_starts) and len(item) < 20:
        return True

    return (
        not item
        or len(item) < 6
        or len(item) > 260
        or lower in blocked_exact
        or any(pattern in lower for pattern in TEMPLATE_NOISE_PATTERNS)
        or any(lower.startswith(prefix) for prefix in blocked_starts)
        or not re.search(r"[a-zA-Z]", item)
    )


def dedupe_items(items: List[str]) -> List[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        item = clean_resume_item(item)
        key = item.lower()
        if item and key not in seen and not is_noise_item(item):
            seen.add(key)
            cleaned.append(item)
    return cleaned


def postprocess_experience_item(item: str) -> str:
    """Minor normalization for experience items to improve readability.

    - collapse whitespace
    - insert a period between merged fragments when a lowercase token
      is followed by a capitalized fragment (common after naive merges)
    - ensure a trailing punctuation mark
    """
    if not item:
        return item
    s = re.sub(r"\s+", " ", item).strip()
    s = s.replace(" ,", ",").replace(" .", ".")
    # Insert a sentence boundary when a fully-lowercase token is followed
    # by an apparent sentence start (Capitalized word). This avoids
    # splitting proper nouns or CamelCase sequences like "Scientific Collaboration".
    def _maybe_insert_period(m: re.Match) -> str:
        prev = m.group(1)
        nxt = m.group(2)
        # Peek at the token after the next to avoid splitting "Web Services" style proper nouns
        rest = s[m.end():]
        next_tokens = re.findall(r"\b([A-Z][a-z]+)\b", rest)
        if next_tokens and next_tokens[0][0].isupper():
            # There's another capitalized token following; likely a proper noun phrase.
            return f"{prev} {nxt}"
        return f"{prev}. {nxt}"

    s = re.sub(r"\b([a-z0-9]+)\b\s+([A-Z][a-z]+)", _maybe_insert_period, s)
    if not re.search(r"[.!?]$", s):
        s = s + "."
    return s.strip()


def enhanced_extract_sections(text: str, file_path: str = None) -> Dict[str, List[str]]:
    """
    Enhanced section extraction that works for ALL resume types
    """
    sections = {
        "skills": [],
        "education": [],
        "experience": [],
        "certifications": []
    }
    
    # STRATEGY 1: Direct table extraction for PDFs
    table_skills = []
    if file_path and file_path.lower().endswith('.pdf'):
        try:
            table_skills = extract_skills_from_pdf_tables(file_path)
            sections["skills"].extend(table_skills)
            print(f"DEBUG: Table extraction found {len(table_skills)} skills")
        except Exception as e:
            print(f"Table extraction failed: {e}")
    
    # STRATEGY 2: Section-aware extraction from real headings.
    for section in ("skills", "education", "experience", "certifications"):
        content = extract_section_content(text, section)
        if not content:
            continue

        print(f"DEBUG: Found {section} section using heading parser")
        if section == "skills":
            items = split_skills_string(content)
        elif section == "education":
            items = parse_education_section(content)
        elif section == "experience":
            items = parse_experience_section(content)
        else:
            items = parse_generic_bullets(content)

        sections[section].extend(items)
    
    # STRATEGY 3: Fallback extraction for sections not found by regex
    if not sections["skills"]:
        skills_fallback = extract_section_fallback(text, "skills")
        sections["skills"].extend(skills_fallback)
    
    if not sections["education"]:
        education_fallback = extract_section_fallback(text, "education")
        sections["education"].extend(education_fallback)
    if not sections["education"]:
        sections["education"].extend(extract_education_from_full_text(text))
    sections["education"] = enrich_education_with_nearby_degree(text, sections["education"])
    two_column_education = extract_two_column_education(text)
    if two_column_education and is_weak_education(sections["education"]):
        sections["education"] = two_column_education
    
    if not sections["experience"]:
        experience_fallback = extract_section_fallback(text, "experience")
        sections["experience"].extend(experience_fallback)
    two_column_experience = extract_two_column_experience(text)
    if two_column_experience and not sections["experience"]:
        sections["experience"] = two_column_experience

    # STRATEGY 4: Always add full-text keyword scanning to recover technical skills
    text_skills = extract_skills_from_text_keywords(text)
    sections["skills"].extend(text_skills)
    print(f"DEBUG: Keyword extraction found {len(text_skills)} skills")
    
    # Clean and deduplicate skills
    if sections["skills"]:
        sections["skills"] = clean_skill_list(sections["skills"])
        print(f"🎯 Final skills after cleaning: {len(sections['skills'])} skills")

    sections["education"] = dedupe_items(sections["education"])
    sections["experience"] = dedupe_items(sections["experience"])
    sections["certifications"] = dedupe_items(sections["certifications"])
    # If an education heading exists but the parser found no content, try
    # capturing nearby lines to infer education; otherwise present a placeholder
    if not sections["education"] and heading_present_in_text(text, "education"):
        nearby = capture_nearby_after_heading(text, "education")
        if nearby:
            sections["education"].extend(parse_education_section(nearby))
        else:
            sections["education"] = ["—"]

    return sections 

def extract_section_fallback(text: str, section: str) -> List[str]:
    """Robust fallback method for various section headers"""
    content = extract_section_content(text, section)
    if content:
        print(f"DEBUG: Fallback found {section} section with heading parser")
        if section == "skills":
            return split_skills_string(content)
        if section == "education":
            return parse_education_section(content)
        if section == "experience":
            return parse_experience_section(content)
        return parse_generic_bullets(content)
    
    return []


def parse_generic_bullets(content: str) -> List[str]:
    items = []
    current = ""

    for raw_line in content.splitlines():
        line = clean_resume_item(raw_line)
        if not line:
            continue

        starts_new = bool(re.match(r"^\s*(?:[•▪*–—¢-]|\d+[.)])\s+", raw_line))
        if starts_new:
            if current:
                items.append(current)
            current = line
        elif current and len(line) < 140:
            current = f"{current} {line}"
        elif not current:
            current = line

    if current:
        items.append(current)

    return dedupe_items(items)


def parse_education_section(content: str) -> List[str]:
    """Parse education section focusing on degree information"""
    items = []
    lines = [clean_resume_item(line) for line in content.split('\n') if clean_resume_item(line)]

    degree_start = re.compile(
        r"\b("
        r"bachelor|bsc|b\.sc|bs\.?|master|msc|m\.sc|ms\.?|phd|doctorate|"
        r"diploma|degree|computer science engineering|higher secondary|"
        r"proficiency certificate|school leaving certificate|slc|intermediate"
        r")\b",
        re.IGNORECASE,
    )
    education_clue = re.compile(
        r"\b(university|college|campus|school|board|tribhuvan|certificate|science|engineering|\d{4})\b",
        re.IGNORECASE,
    )
    grade_clue = re.compile(
        r"\b(first|second|third|division|aggregate|gpa|percentage|percent|%)\b",
        re.IGNORECASE,
    )
    date_clue = re.compile(
        r"\b\d{1,2}/\d{4}\s*(?:-|to|–|—)\s*\d{1,2}/\d{4}\b|"
        r"\b\d{4}\s*(?:-|to|–|—)\s*(?:\d{4}|present|now)\b|"
        r"\b\d{4}\b",
        re.IGNORECASE,
    )
    skip_line = re.compile(
        r"programming languages|data science tools|machine learning|web development|"
        r"database management|other tools|technical|skills|projects?|qwikresume|"
        r"free resume template|copyright|usage guidelines|guidelines",
        re.IGNORECASE,
    )

    current_item = ""
    for line in lines:
        if not line or skip_line.search(line):
            continue
        if is_noise_item(line) and not date_clue.search(line):
            continue

        if degree_start.search(line):
            if current_item:
                items.append(current_item)
            current_item = line
        elif current_item and len(line) < 120 and (
            education_clue.search(line)
            or grade_clue.search(line)
            or date_clue.search(line)
            or "," in line
            or line.startswith("(")
            or line.istitle()
        ):
            current_item += " " + line
        elif not current_item and education_clue.search(line) and len(line) < 150:
            current_item = line
    
    if current_item:
        items.append(current_item)
    
    if not items:
        items = [
            clean_resume_item(item)
            for item in re.split(r'[\n•]', content)
            if education_clue.search(item) and len(clean_resume_item(item)) < 200
        ]

    return dedupe_items(items)


def parse_experience_section(content: str) -> List[str]:
    """Parse experience into job-level entries instead of sentence fragments."""
    role_or_date = re.compile(
        r"\b("
        r"manager|director|administrator|officer|engineer|developer|analyst|"
        r"consultant|specialist|intern|lecturer|assistant|representative|lead"
        r")\b|"
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}\b|"
        r"\b\d{4}\s*(?:-|to|–|—)\s*(?:\d{4}|present|now)\b|"
        r"\bfrom\s+.+?\s+to\s+.+",
        re.IGNORECASE,
    )

    raw_lines = [line for line in content.splitlines() if line.strip()]
    if raw_lines and not any(role_or_date.search(clean_resume_item(line)) for line in raw_lines):
        return parse_experience_bullets(content)

    items = []
    current = ""
    skip_line = re.compile(
        r"^(?:o\s+)?(?:led|leading|provided|conducted|contributed|acted|supported|"
        r"gathering|create|uploading|accomplishment|completed|passionate)\b",
        re.IGNORECASE,
    )
    skipping_detail = False

    for raw_line in raw_lines:
        line = clean_resume_item(raw_line)
        starts_new = bool(re.match(r"^\s*(?:[•▪*–—¢-]|\d+[.)])\s+", raw_line))
        sub_bullet = bool(re.match(r"^\s*o\s+", raw_line, re.IGNORECASE))

        if not line or is_noise_item(line):
            continue
        if sub_bullet or skip_line.search(line):
            skipping_detail = True
            continue

        has_role_or_date = bool(role_or_date.search(line))
        if skipping_detail and not starts_new and not has_role_or_date:
            continue
        if starts_new or has_role_or_date:
            skipping_detail = False

        if starts_new:
            if has_role_or_date:
                if current:
                    items.append(current)
                current = line
            elif current:
                current = f"{current} {line}"
            else:
                current = line
        elif current and len(line) < 140:
            current = f"{current} {line}"
        elif has_role_or_date:
            if current:
                items.append(current)
            current = line

    if current:
        items.append(current)

    items = dedupe_items(items)
    if items:
        # Post-process for readability
        return [postprocess_experience_item(i) for i in items]

    return parse_experience_bullets(content)


def parse_experience_bullets(content: str) -> List[str]:
    """Fallback for internship/project resumes where experience is accomplishment bullets."""
    items = []
    current = ""
    stop_line = re.compile(
        r"^(?:machine learning\s*&\s*data science|completed multiple courses|"
        r"certifications?|courses?|web development with|data visualization with)\b",
        re.IGNORECASE,
    )

    for raw_line in content.splitlines():
        line = clean_resume_item(raw_line)
        if not line or is_noise_item(line):
            continue
        if stop_line.search(line):
            break

        starts_new = bool(re.match(r"^\s*(?:[•▪*–—¢-]|\d+[.)])\s+", raw_line))
        if starts_new:
            previous_incomplete = bool(current and not re.search(r"[.!?]$", current))
            if current and (line[0].islower() or previous_incomplete or len(line) < 60):
                current = f"{current} {line}"
            else:
                if current:
                    items.append(current)
                current = line
        elif current and len(line) < 120:
            current = f"{current} {line}"
        elif not current and len(line) < 140:
            current = line

    if current:
        items.append(current)

    items = dedupe_items(items)
    # Post-process for readability
    return [postprocess_experience_item(i) for i in items]


def find_degree_before_education(text: str) -> str:
    degree_re = re.compile(
        r"\b("
        r"bachelor|bsc|b\.sc|bse|bs\.?|master|msc|m\.sc|ms\.?|phd|doctorate|"
        r"diploma|degree|computer science engineering|higher secondary|"
        r"proficiency certificate|school leaving certificate|slc|intermediate"
        r")\b",
        re.IGNORECASE,
    )
    lines = [clean_resume_item(line) for line in text.splitlines()]

    for index, line in enumerate(lines):
        heading = detect_section_heading(line)
        if not heading or heading[0] != "education":
            continue

        for previous in reversed(lines[max(0, index - 5):index]):
            if degree_re.search(previous) and not is_noise_item(previous):
                return previous

    return ""


def enrich_education_with_nearby_degree(text: str, items: List[str]) -> List[str]:
    degree = find_degree_before_education(text)
    if not degree or not items:
        return items

    degree_key = degree.lower()
    if any(degree_key in item.lower() for item in items):
        return items

    enriched = [f"{degree} - {items[0]}"]
    enriched.extend(items[1:])
    return enriched


def extract_education_from_full_text(text: str) -> List[str]:
    """Recover education from two-column PDFs where headings and content interleave."""
    candidate_lines = []
    degree_or_school = re.compile(
        r"\b("
        r"bachelor|bsc|b\.sc|master|msc|m\.sc|phd|computer science engineering|"
        r"higher secondary|proficiency certificate|school leaving certificate|slc|"
        r"university|college|campus|school"
        r")\b",
        re.IGNORECASE,
    )

    for line in text.splitlines():
        line = clean_resume_item(line)
        if not line or is_noise_item(line):
            continue
        heading = detect_section_heading(line)
        if heading and heading[0] != "education":
            continue
        if re.search(r"\b(project name|client:|developer|uidesign|appstore|parent-teacher)\b", line, re.IGNORECASE):
            continue
        if re.match(r"^(?:experience|projects?|languages?)\b", line, re.IGNORECASE):
            continue
        if degree_or_school.search(line) and len(line) < 160:
            candidate_lines.append(line)

    return parse_education_section("\n".join(candidate_lines))


def heading_present_in_text(text: str, target_section: str) -> bool:
    for line in text.splitlines():
        h = detect_section_heading(line)
        if h and h[0] == target_section:
            return True
    return False


def capture_nearby_after_heading(text: str, target_section: str, lookahead: int = 6) -> str:
    """When a heading exists but has no direct content, capture the next few
    non-empty non-separator lines to infer section content."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        h = detect_section_heading(line)
        if not h or h[0] != target_section:
            continue

        captured = []
        for nxt in range(idx + 1, min(len(lines), idx + 1 + lookahead)):
            cand = lines[nxt].strip()
            if not cand:
                continue
            # stop if we hit another heading — no more education content
            if detect_section_heading(cand):
                break
            # skip purely decorative separators
            if re.fullmatch(r"[\u2013\u2014\-–——\s]+|[•▪*]+", cand):
                continue
            captured.append(cand)
        if captured:
            return "\n".join(captured)
    return ""


def is_weak_education(items: List[str]) -> bool:
    if not items:
        return True
    if len(items) > 1:
        return False
    item = clean_resume_item(items[0])
    return len(item.split()) <= 5 or item.lower().endswith(" of")


def extract_education_experience_block(text: str) -> list[str]:
    """Return the mixed education/experience area from two-column PDFs."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^\s*education\s*$", line, re.IGNORECASE):
            start = index + 1
            break

    if start is None:
        return []

    block = []
    for line in lines[start:]:
        if re.match(r"^\s*(projects?|languages?|certifications?|basic information)\s*$", line, re.IGNORECASE):
            break
        block.append(line)

    has_two_column_spacing = any(re.search(r"\S\s{8,}\S", line) for line in block)
    has_experience_marker = any(re.match(r"^\s*experience\s{3,}", line, re.IGNORECASE) for line in block)
    return block if has_two_column_spacing or has_experience_marker else []


def split_two_column_line(raw_line: str) -> str:
    """Prefer the right-side column when PDF text contains a wide spacing gap."""
    parts = [part.strip() for part in re.split(r"\s{8,}", raw_line) if part.strip()]
    if len(parts) >= 2:
        return parts[-1]
    return raw_line.strip()


def extract_two_column_education(text: str) -> List[str]:
    block = extract_education_experience_block(text)
    if not block:
        return []

    degree_start = re.compile(
        r"\b("
        r"computer science engineering|higher secondary education|bachelor|bsc|b\.sc|"
        r"master|msc|m\.sc|phd|proficiency certificate|school leaving certificate|slc"
        r")\b",
        re.IGNORECASE,
    )
    education_detail = re.compile(
        r"\b(university|school|college|technology|\d{4}|aggregate|division|%)\b",
        re.IGNORECASE,
    )
    experience_noise = re.compile(
        r"\b(developer|solutions|llc|responsible|gathering|uidesign|uploading|appstore|"
        r"total end-end|xcode|project|client|role:|organization:)\b",
        re.IGNORECASE,
    )

    items = []
    current = ""
    for raw_line in block:
        candidate = clean_resume_item(split_two_column_line(raw_line))
        if not candidate or is_noise_item(candidate):
            continue
        if re.match(r"^experience\b", candidate, re.IGNORECASE):
            candidate = clean_resume_item(re.sub(r"^experience\b", "", candidate, flags=re.IGNORECASE))
        if not candidate or experience_noise.search(candidate):
            continue

        if degree_start.search(candidate):
            if current:
                items.append(current)
            current = candidate
        elif current and len(candidate) < 120 and education_detail.search(candidate):
            current = f"{current} {candidate}"
        elif not current and degree_start.search(candidate):
            current = candidate

    if current:
        items.append(current)

    return dedupe_items(items)


def extract_two_column_experience(text: str) -> List[str]:
    block = extract_education_experience_block(text)
    if not block:
        return []

    lines = [clean_resume_item(split_two_column_line(line)) for line in block]
    lines = [line for line in lines if line and not is_noise_item(line)]

    role_re = re.compile(r"\b(?:ios|android|software|web|mobile)?\s*developer\b", re.IGNORECASE)
    company_date_re = re.compile(
        r"(?P<company>.+?)\s+"
        r"(?P<date>(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}\s*[-–—]\s*(?:present|now|\w+\s+\d{4}))",
        re.IGNORECASE,
    )

    items = []
    for index, line in enumerate(lines):
        if not role_re.search(line):
            continue

        for next_line in lines[index + 1:index + 5]:
            match = company_date_re.search(next_line)
            if not match:
                continue

            role = clean_resume_item(line)
            company = clean_resume_item(match.group("company"))
            date_range = clean_resume_item(match.group("date"))
            items.append(f"{role}, {company}, {date_range}")
            break

    return dedupe_items(items)


def extract_skills_from_text_keywords(text: str) -> List[str]:
    """Extract skills by scanning entire text for keywords"""
    skills_found = set()
    
    # Common technical skills
    technical_skills = [
        'cyber security', 'ethical hacking', 'penetration testing', 'vulnerability assessments',
        'security risk assessment', 'server hardening', 'application hardening', 'security baseline configuration',
        'is audit', 'information security', 'data protection', 'vapt', 'risk analysis',
        # Programming Languages
        'python', 'java', 'javascript', 'typescript', 'c++', 'c#', 'php', 'ruby', 'go', 'swift', 'kotlin',
        'r', 'scala', 'rust', 'matlab', 'perl', 'bash', 'shell', 'powershell',
        
        # Data Science & ML
        'machine learning', 'deep learning', 'artificial intelligence', 'ai', 'data science', 'data analysis',
        'data visualization', 'statistical analysis', 'predictive modeling', 'regression', 'classification',
        'clustering', 'natural language processing', 'nlp', 'computer vision', 'neural networks', 'time series',
        'a/b testing', 'hypothesis testing', 'exploratory data analysis', 'eda', 'feature engineering',
        'model selection', 'cross validation', 'hyperparameter tuning', 'ensemble methods',
        # Data Tools
        'pandas', 'numpy', 'scipy', 'scikit-learn', 'sklearn', 'tensorflow', 'pytorch', 'keras', 'mxnet',
        'matplotlib', 'seaborn', 'plotly', 'bokeh', 'd3.js', 'ggplot2', 'tableau', 'power bi', 'powerbi',
        'qlik', 'looker', 'jupyter', 'google colab', 'rstudio', 'spss', 'sas', 'stata',
        
        # Databases
        'sql', 'mysql', 'postgresql', 'postgres', 'oracle', 'sql server', 'mongodb', 'redis', 'couchbase',
        'dynamodb', 'cassandra', 'neo4j', 'sqlite', 'firebase', 'cosmos db', 'bigquery', 'snowflake',
        
        # Big Data
        'spark', 'pyspark', 'hadoop', 'hive', 'kafka', 'storm', 'flink', 'beam', 'airflow', 'luigi',
        'presto', 'hbase', 'cassandra', 'elasticsearch', 'splunk',
        # Cloud & DevOps
        'aws', 'amazon web services', 'azure', 'microsoft azure', 'gcp', 'google cloud', 'docker', 'kubernetes',
        'jenkins', 'git', 'github', 'gitlab', 'bitbucket', 'terraform', 'ansible', 'puppet', 'chef',
        'ci/cd', 'continuous integration', 'continuous deployment', 'devops', 'mlops',
        
        # Web Development
        'html', 'css', 'react', 'angular', 'vue', 'node', 'node.js', 'express', 'django', 'flask', 'spring',
        'laravel', 'ruby on rails', 'asp.net', 'php', 'wordpress', 'drupal', 'joomla',
        
        # Mobile Development
        'android', 'ios', 'swift', 'react native', 'flutter', 'xamarin', 'ionic', 'cordova',
        
        # Tools & Software
        'excel', 'powerpoint', 'word', 'outlook', 'sharepoint', 'jira', 'confluence', 'slack', 'teams',
        'zoom', 'photoshop', 'illustrator', 'figma', 'sketch', 'invision',
        'adobe xd', 'canva', 'notion', 'evernote',
        # Methodologies
        'agile', 'scrum', 'kanban', 'waterfall', 'lean', 'six sigma', 'devops',
        
        # Soft Skills
        'communication', 'problem solving', 'teamwork', 'leadership', 'project management', 'time management',
        'critical thinking', 'analytical skills', 'creativity', 'adaptability', 'presentation', 'negotiation'
    ]
    
    text_lower = text.lower()
    
    for skill in technical_skills:
        if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
            skills_found.add(skill)
    
    return list(skills_found)

# KEEP YOUR EXISTING helper functions
def split_skills_string(skills_text: str) -> List[str]:
    if not skills_text:
        return []
    
    print(f"DEBUG: split_skills_string input: {skills_text[:200]}...")
    
    # FIRST: Try to extract bullet points with multi-word skills
    lines = [line.strip() for line in skills_text.split('\n') if line.strip()]
    
    bullet_skills = []
    for line in lines:
        # Skip lines that are too long (paragraphs)
        if len(line) > 80:
            continue
            
        # Remove ALL types of bullets including ▪ 
        clean_line = re.sub(r'^[\-\•\*\–\—\▪]\s*', '', line)
        
        # Check if this looks like a skill (not a sentence, not too long)
        if (len(clean_line) <= 50 and 
            not re.search(r'[.!?]\s*[A-Z]', clean_line) and  # Not a sentence
            not clean_line.endswith('.') and  # Not ending with period
            clean_line and not clean_line.isdigit() and
            len(clean_line) > 2):  # At least 3 characters
            
            skill = clean_line.strip()
            if skill:
                bullet_skills.append(skill)

    delimiter_skills = []
    for line in lines:
        clean_line = re.sub(r'^[\-\•\*\–\—\▪]\s*', '', line)
        if any(delimiter in clean_line for delimiter in [',', ';', '|', '&', '/']):
            parts = re.split(r'[,;|&/]', clean_line)
            for part in parts:
                skill = part.strip()
                if 2 < len(skill) <= 40 and not skill.isdigit():
                    delimiter_skills.append(skill)
    
    # Prefer delimiter-separated skills when present; otherwise use concise bullets.
    if delimiter_skills:
        print(f"DEBUG: Found {len(delimiter_skills)} delimiter skills: {delimiter_skills}")
        return delimiter_skills

    if bullet_skills:
        print(f"DEBUG: Found {len(bullet_skills)} bullet skills: {bullet_skills}")
        return bullet_skills
    
    # SECOND: If no bullets found, use SIMPLE space-based splitting but preserve multi-word
    skills = []
    lines = [line.strip() for line in skills_text.split('\n') if line.strip()]
    
    for line in lines:
        # Remove bullets
        clean_line = re.sub(r'^[\-\•\*\–\—\▪]\s*', '', line)
        
        # If line is short and looks like skills, use the whole line
        if len(clean_line) <= 50 and len(clean_line) > 2:
            skills.append(clean_line)
        else:
            # Fallback to your original delimiter approach
            delimiters = [',', ';', '/', '|', '&']
            for delimiter in delimiters:
                if delimiter in clean_line:
                    parts = clean_line.split(delimiter)
                    for part in parts:
                        skill = part.strip()
                        if skill and len(skill) > 2 and not skill.isdigit():
                            skills.append(skill)
                    break
            else:
                # If no delimiters, try to preserve multi-word skills
                # Look for patterns like "Cyber Security", "Ethical Hacking"
                potential_skills = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[A-Z][a-z]+', clean_line)
                for skill in potential_skills:
                    if len(skill) > 2 and len(skill) <= 30:
                        skills.append(skill)
    
    # Clean up the skills
    cleaned_skills = []
    for skill in skills:
        skill = re.sub(r'^\W+|\W+$', '', skill)  # Remove surrounding punctuation
        if skill and len(skill) > 2:
            cleaned_skills.append(skill)
    
    print(f"DEBUG: Final skills from split_skills_string: {cleaned_skills}")
    return cleaned_skills

def split_skills_by_uppercase(text: str) -> List[str]:
    skills = re.findall(r'[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)', text)
    return [skill.strip() for skill in skills if skill.strip()]
