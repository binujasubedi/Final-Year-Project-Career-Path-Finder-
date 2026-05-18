from __future__ import annotations
from pathlib import Path
import base64
import html
import re
import sys
import time
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime
import json

PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

try:
    from src.parsing.ml.skill_matcher_db import analyze_resume, load_skill_dataset_from_db
    from src.database import AuthService, ResumeRepository, SkillRepository, init_supabase
except ImportError as e:
    st.error(f"Import error: {e}")
    st.stop()

UPLOADS_DIR = PROJ_ROOT / "app" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
ANALYSES_CACHE_PATH = UPLOADS_DIR / "local_analyses.json"
AUTH_COOKIE_NAME = "smart_career_auth"
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
PARSER_OUTPUT_VERSION = "education-experience-v6"


def safe_upload_name(filename: str) -> str:
    return Path(filename).name.replace(" ", "_")


def _session_value(session: object, key: str) -> str | None:
    if isinstance(session, dict):
        return session.get(key)
    return getattr(session, key, None)


def auth_cookie_payload(session: object) -> dict:
    return {
        "access_token": _session_value(session, "access_token"),
        "refresh_token": _session_value(session, "refresh_token"),
    }


def write_auth_cookie(session: object) -> None:
    payload = auth_cookie_payload(session)
    if not payload.get("access_token") or not payload.get("refresh_token"):
        return

    cookie_value = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    components.html(
        f"""
        <script>
            const cookieValue = {json.dumps(cookie_value)};
            const authCookie = "{AUTH_COOKIE_NAME}=" + cookieValue
                + "; path=/; max-age={AUTH_COOKIE_MAX_AGE}; SameSite=Lax";
            document.cookie = authCookie;
            try {{
                window.parent.document.cookie = authCookie;
            }} catch (error) {{}}
        </script>
        """,
        height=0,
    )


def clear_auth_cookie() -> None:
    components.html(
        f"""
        <script>
            const clearCookie = "{AUTH_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
            document.cookie = clearCookie;
            try {{
                window.parent.document.cookie = clearCookie;
            }} catch (error) {{}}
        </script>
        """,
        height=0,
    )


def read_auth_cookie() -> dict:
    cookie_value = st.context.cookies.get(AUTH_COOKIE_NAME)
    if not cookie_value:
        return {}

    try:
        return json.loads(base64.urlsafe_b64decode(cookie_value.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def restore_auth_session_safely(auth_service: AuthService, cookie_session: dict) -> dict | None:
    """Restore auth from persisted tokens, even if Streamlit holds an older AuthService."""
    access_token = cookie_session.get("access_token")
    refresh_token = cookie_session.get("refresh_token")
    if not access_token or not refresh_token:
        return None

    if hasattr(auth_service, "restore_session"):
        return auth_service.restore_session(access_token, refresh_token)

    try:
        response = auth_service.client.auth.set_session(access_token, refresh_token)
        user = getattr(response, "user", None)
        session = getattr(response, "session", None)

        if not user:
            current_user = auth_service.client.auth.get_user()
            user = getattr(current_user, "user", None)

        if user:
            return {
                "success": True,
                "user": user,
                "session": session,
                "message": "Session restored"
            }
    except Exception as e:
        print(f"Error restoring auth session: {e}")

    return {
        "success": False,
        "message": "No active session"
    }


def display_resume_date(resume: dict) -> str:
    """Return a readable upload date from DB data, filename timestamp, or local file metadata."""
    upload_date = resume.get("upload_date")
    if isinstance(upload_date, datetime):
        return upload_date.strftime("%Y-%m-%d")

    if isinstance(upload_date, str) and upload_date.strip():
        try:
            return datetime.fromisoformat(upload_date.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except ValueError:
            return upload_date[:10]

    filename = safe_upload_name(str(resume.get("filename", "")))
    timestamp = filename.split("__", 1)[0]
    try:
        return datetime.strptime(timestamp, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d")
    except ValueError:
        pass

    matching_files = [
        path for path in UPLOADS_DIR.iterdir()
        if path.is_file() and (path.name == filename or path.name.endswith(f"__{filename}"))
    ]
    if matching_files:
        newest_match = max(matching_files, key=lambda path: path.stat().st_mtime)
        return datetime.fromtimestamp(newest_match.stat().st_mtime).strftime("%Y-%m-%d")

    return "Unknown Date"


def is_cv_display_noise(value: object) -> bool:
    text = str(value or "").strip().lower()
    noise_patterns = (
        "qwikresume",
        "free resume template",
        "copyright",
        "usage guidelines",
        "strong academic",
        "it and security domain",
        "professional certifications",
        "developing applications on ios",
        "work experience in swift programming",
        "tools: xcode",
    )
    noise_starts = (
        "having ",
        "experiences ",
        "experience in the",
        "background",
        "with aggregate",
        "with an aggregate",
    )
    noise_exact = {
        "",
        "guidelines",
        "usage",
        "professional",
        "academic",
        "background",
        "c",
    }
    return (
        text in noise_exact
        or any(text.startswith(prefix) for prefix in noise_starts)
        or any(pattern in text for pattern in noise_patterns)
    )


def clean_cv_display_items(items: object, limit: int = 3) -> list[str]:
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list):
        return []

    cleaned = []
    seen = set()
    for item in items:
        text = re.sub(r"\s+", " ", str(item or "")).strip(" •-–—;,")
        if is_cv_display_noise(text):
            continue
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)

    # If filtering removed everything, preserve the original parsed values so the UI
    # can still display education/experience items when the parser found them.
    if not cleaned and isinstance(items, list):
        for item in items:
            text = re.sub(r"\s+", " ", str(item or "")).strip(" •-–—;," )
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                cleaned.append(text)

    return cleaned[:limit]


def show_resume_viewer(file_path: Path, filename: str, file_type: str) -> None:
    file_bytes = file_path.read_bytes()
    normalized_type = file_type.lower().strip(".")
    encoded_file = base64.b64encode(file_bytes).decode("utf-8")
    escaped_filename = html.escape(filename)
    mime = (
        "application/pdf"
        if normalized_type == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    st.download_button(
        "Download Resume",
        data=file_bytes,
        file_name=filename,
        mime=mime,
        width="stretch",
        key=f"download_uploaded_resume_{file_path.name}"
    )

    if normalized_type != "pdf":
        st.info("DOCX preview is not available here. Download the resume to view the original file.")
        return

    st.markdown(
        f"""
        <iframe
            title="{escaped_filename}"
            src="data:application/pdf;base64,{encoded_file}"
            width="100%"
            height="720"
            style="margin-top: 14px; border: 1px solid #e5e7eb; border-radius: 8px; background: white;"
        ></iframe>
        """,
        unsafe_allow_html=True
    )


def load_local_analyses() -> list[dict]:
    """Load locally cached analyses for offline analytics."""
    if not ANALYSES_CACHE_PATH.exists():
        return []

    try:
        return json.loads(ANALYSES_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def persist_local_analyses(analyses: list[dict]) -> None:
    """Persist offline analyses cache to disk."""
    try:
        ANALYSES_CACHE_PATH.write_text(
            json.dumps(analyses, ensure_ascii=True, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass

st.set_page_config(
    page_title="Smart Career",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Fresh, simple UI theme
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    :root {
        --primary: #0f766e;
        --primary-dark: #115e59;
        --accent: #f97316;
        --accent-soft: #fff7ed;
        --ink: #102026;
        --muted: #60707a;
        --line: #d9e5e4;
        --panel: #ffffff;
        --soft: #f6faf9;
        --navy: #102a43;
        --mint: #dff7ef;
    }

    * {
        font-family: 'Inter', sans-serif;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    .stApp {
        background:
            linear-gradient(180deg, #f7fbfa 0%, #eef7f4 48%, #f8fafc 100%);
        color: var(--ink);
    }

    .auth-page {
        max-width: 1080px;
        margin: 36px auto 24px;
        padding: 12px;
    }

    .auth-brand-panel {
        min-height: 560px;
        padding: 42px;
        border-radius: 8px;
        color: #ffffff;
        background:
            linear-gradient(135deg, #102a43 0%, #0f766e 58%, #115e59 100%);
        box-shadow: 0 22px 55px rgba(15, 23, 42, 0.18);
        border: 1px solid rgba(255, 255, 255, 0.18);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        overflow: hidden;
    }

    .auth-kicker {
        display: inline-flex;
        align-items: center;
        width: fit-content;
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.14);
        border: 1px solid rgba(255, 255, 255, 0.24);
        color: #dbeafe;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.2px;
        margin-bottom: 28px;
    }

    .auth-brand-title {
        margin: 0 0 14px;
        max-width: 460px;
        color: #ffffff;
        font-size: 3rem;
        line-height: 1.02;
        font-weight: 800;
        letter-spacing: 0;
    }

    .auth-brand-copy {
        max-width: 440px;
        color: rgba(255, 255, 255, 0.84);
        font-size: 1rem;
        line-height: 1.65;
        margin: 0;
    }

    .auth-feature-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin-top: 36px;
    }

    .auth-feature {
        padding: 16px;
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.18);
        backdrop-filter: blur(12px);
    }

    .auth-feature strong {
        display: block;
        color: #ffffff;
        font-size: 1.35rem;
        margin-bottom: 4px;
    }

    .auth-feature span {
        color: rgba(255, 255, 255, 0.78);
        font-size: 0.82rem;
        line-height: 1.35;
    }

    .auth-form-panel {
        display: none;
    }

    [data-testid="column"]:has(.auth-form-anchor) {
        min-height: 560px;
        padding: 34px 36px 30px;
        border-radius: 8px;
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
        border: 1px solid #d7e5df;
        box-shadow: 0 22px 55px rgba(15, 118, 110, 0.13);
        align-self: stretch;
    }

    [data-testid="column"]:has(.auth-brand-panel) {
        align-self: stretch;
    }

    .auth-form-anchor {
        display: none;
    }

    .login-container {
        margin: 0 0 22px;
        background: transparent;
        border-radius: 0;
        padding: 0;
        box-shadow: none;
        border: none;
        animation: fadeInUp 0.6s ease;
    }

    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .login-header {
        text-align: left;
        margin-bottom: 18px;
    }

    .login-title {
        font-size: 1.9rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 8px;
        letter-spacing: 0;
        line-height: 1.12;
    }

    .login-subtitle {
        color: var(--muted);
        font-size: 0.95rem;
        line-height: 1.5;
        font-weight: 400;
    }

    .auth-form-kicker {
        display: inline-flex;
        align-items: center;
        width: fit-content;
        padding: 7px 10px;
        border-radius: 999px;
        background: #fff7ed;
        color: #c2410c;
        border: 1px solid #fed7aa;
        font-size: 0.78rem;
        font-weight: 800;
        margin-bottom: 14px;
    }

    .dashboard-shell {
        max-width: 1240px;
        margin: 0 auto;
        padding: 0 18px 16px;
    }

    .dashboard-topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 18px;
        margin: 8px 0 18px;
        padding: 14px 18px;
        border: 1px solid rgba(16, 42, 67, 0.08);
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.82);
        box-shadow: 0 18px 42px rgba(16, 42, 67, 0.08);
        backdrop-filter: blur(18px);
    }

    .brand-lockup {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .brand-mark {
        display: grid;
        place-items: center;
        width: 42px;
        height: 42px;
        border-radius: 8px;
        background: var(--navy);
        color: #ffffff;
        font-weight: 900;
        box-shadow: 0 12px 24px rgba(16, 42, 67, 0.20);
    }

    .brand-title {
        color: var(--ink);
        font-size: 1rem;
        font-weight: 900;
        line-height: 1.1;
        margin: 0;
    }

    .brand-subtitle {
        color: var(--muted);
        font-size: 0.82rem;
        font-weight: 700;
        margin-top: 3px;
    }

    .dashboard-hero {
        position: relative;
        overflow: hidden;
        min-height: 255px;
        margin-bottom: 22px;
        padding: 34px;
        border-radius: 8px;
        color: #ffffff;
        border: 1px solid rgba(255, 255, 255, 0.26);
        background:
            linear-gradient(120deg, #102a43 0%, #0f766e 62%, #115e59 100%);
        box-shadow: 0 26px 70px rgba(16, 42, 67, 0.24);
    }

    .hero-kicker {
        display: inline-flex;
        align-items: center;
        width: fit-content;
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.14);
        border: 1px solid rgba(255, 255, 255, 0.20);
        color: #dff7ef;
        font-size: 0.78rem;
        font-weight: 850;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        margin-bottom: 18px;
    }

    .hero-title {
        max-width: 700px;
        margin: 0;
        color: #ffffff;
        font-size: 2.85rem;
        line-height: 1.03;
        font-weight: 900;
        letter-spacing: 0;
    }

    .hero-copy {
        max-width: 620px;
        margin: 16px 0 0;
        color: rgba(255, 255, 255, 0.82);
        font-size: 1rem;
        line-height: 1.65;
        font-weight: 500;
    }

    .hero-strip {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 28px;
    }

    .hero-pill {
        display: inline-flex;
        gap: 8px;
        align-items: center;
        padding: 9px 12px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.14);
        color: rgba(255, 255, 255, 0.88);
        border: 1px solid rgba(255, 255, 255, 0.18);
        font-size: 0.84rem;
        font-weight: 750;
    }

    .stat-card {
        min-height: 132px;
        background: rgba(255, 255, 255, 0.92);
        padding: 18px 18px 16px;
        border-radius: 8px;
        color: var(--ink);
        box-shadow: 0 16px 34px rgba(16, 42, 67, 0.08);
        transition: all 0.24s ease;
        border: 1px solid rgba(16, 42, 67, 0.08);
    }

    .stat-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 22px 48px rgba(16, 42, 67, 0.12);
        border-color: rgba(15, 118, 110, 0.28);
    }

    .stat-label {
        color: var(--muted);
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.55px;
        font-weight: 850;
    }

    .stat-number {
        margin: 12px 0 6px;
        color: var(--ink);
        font-size: 2.2rem;
        line-height: 1;
        font-weight: 900;
    }

    .stat-subtext {
        color: var(--primary);
        font-size: 0.78rem;
        font-weight: 800;
    }

    .section-header {
        display: flex;
        align-items: center;
        gap: 10px;
        color: var(--ink);
        font-size: 1.18rem;
        font-weight: 900;
        margin: 34px 0 18px 0;
        padding: 0 0 12px 0;
        border-bottom: 1px solid rgba(16, 42, 67, 0.10);
    }

    .stButton > button,
    .stDownloadButton > button {
        background: linear-gradient(135deg, var(--primary), var(--primary-dark)) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 8px;
        padding: 12px 30px;
        font-weight: 850;
        font-size: 1rem;
        transition: all 0.3s ease;
        box-shadow: 0 12px 24px rgba(15, 118, 110, 0.20);
        width: 100%;
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover {
        transform: translateY(-2px);
        background: linear-gradient(135deg, #0d9488, var(--primary-dark)) !important;
        color: #ffffff !important;
        box-shadow: 0 16px 30px rgba(15, 118, 110, 0.25);
    }

    .stButton > button *,
    .stDownloadButton > button * {
        color: #ffffff !important;
    }

    .secondary-btn button,
    .secondary-btn button * {
        background: #ffffff !important;
        color: var(--primary) !important;
        border: 1px solid #bfdbfe !important;
        box-shadow: none !important;
    }

    .secondary-btn button:hover,
    .secondary-btn button:hover * {
        background: #eff6ff !important;
        color: var(--primary-dark) !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(255, 255, 255, 0.76);
        padding: 6px;
        border-radius: 8px;
        border: 1px solid rgba(16, 42, 67, 0.08);
        box-shadow: 0 10px 26px rgba(16, 42, 67, 0.06);
    }

    .stTabs [data-baseweb="tab"] {
        height: 48px;
        background: transparent;
        border-radius: 6px;
        padding: 10px 20px;
        font-weight: 850;
        color: #526872;
        border: none;
    }

    .stTabs [aria-selected="true"] {
        background: #ffffff;
        color: var(--primary) !important;
        box-shadow: 0 8px 18px rgba(16, 42, 67, 0.10);
    }

    .stTextInput > div > div > input {
        border-radius: 8px;
        border: 1px solid var(--line);
        padding: 12px 16px;
        font-size: 1rem;
        transition: all 0.3s ease;
    }

    .stTextInput > div > div > input:focus {
        border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
    }

    [data-testid="column"]:has(.auth-form-anchor) .stTabs [data-baseweb="tab-list"] {
        background: #f8fafc;
        border: 1px solid #d7e5df;
        margin-bottom: 8px;
        padding: 5px;
        gap: 4px;
        width: fit-content;
    }

    [data-testid="column"]:has(.auth-form-anchor) .stTabs [data-baseweb="tab"] {
        height: 42px;
        min-width: 128px;
        padding: 8px 14px;
        color: #475569 !important;
    }

    [data-testid="column"]:has(.auth-form-anchor) .stTabs [aria-selected="true"] {
        background: #0f766e;
        color: #ffffff !important;
        box-shadow: 0 8px 18px rgba(15, 118, 110, 0.18);
    }

    [data-testid="column"]:has(.auth-form-anchor) .stTextInput label {
        color: #334155 !important;
        font-size: 0.84rem !important;
        font-weight: 700 !important;
    }

    [data-testid="column"]:has(.auth-form-anchor) [data-testid="stTextInput"] {
        margin-bottom: 8px;
    }

    [data-testid="column"]:has(.auth-form-anchor) [data-baseweb="input"] {
        min-height: 48px;
        background: #ffffff !important;
        border: 1px solid #cbded8 !important;
        border-radius: 8px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }

    [data-testid="column"]:has(.auth-form-anchor) [data-baseweb="input"]:focus-within {
        border-color: #f97316 !important;
        box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.14);
    }

    [data-testid="column"]:has(.auth-form-anchor) .stTextInput > div > div > input {
        min-height: 48px;
        background: #ffffff !important;
        color: var(--ink) !important;
        border-color: transparent;
    }

    [data-testid="column"]:has(.auth-form-anchor) .stTextInput > div > div > input:focus {
        background: #ffffff;
    }

    [data-testid="column"]:has(.auth-form-anchor) [data-baseweb="input"] svg {
        color: #64748b !important;
        fill: #64748b !important;
    }

    [data-testid="column"]:has(.auth-form-anchor) [data-testid="stForm"] {
        border: 0;
        padding: 0;
    }

    [data-testid="column"]:has(.auth-form-anchor) [data-testid="stFormSubmitButton"] button {
        min-height: 48px;
        margin-top: 8px;
        background: linear-gradient(135deg, #f97316, #0f766e) !important;
        color: #ffffff !important;
        border: 0 !important;
        border-radius: 8px !important;
        font-weight: 800 !important;
        box-shadow: 0 14px 24px rgba(249, 115, 22, 0.20);
    }

    [data-testid="column"]:has(.auth-form-anchor) [data-testid="stFormSubmitButton"] button:hover {
        transform: translateY(-1px);
        box-shadow: 0 18px 28px rgba(15, 118, 110, 0.24);
    }

    /* Force Streamlit/BaseWeb auth controls out of the default dark widget styling. */
    [data-testid="stTextInput"] label,
    [data-testid="stTextInput"] label p {
        color: #334155 !important;
        font-size: 0.86rem !important;
        font-weight: 800 !important;
    }

    [data-testid="stTextInput"] [data-baseweb="input"] {
        min-height: 52px !important;
        background: #ffffff !important;
        border: 1px solid #cbded8 !important;
        border-radius: 8px !important;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.04) !important;
        overflow: hidden !important;
    }

    [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {
        border-color: #f97316 !important;
        box-shadow: 0 0 0 4px rgba(249, 115, 22, 0.14) !important;
    }

    [data-testid="stTextInput"] input {
        min-height: 50px !important;
        background: #ffffff !important;
        color: #0f172a !important;
        -webkit-text-fill-color: #0f172a !important;
        border: 0 !important;
        box-shadow: none !important;
        font-size: 1rem !important;
        font-weight: 650 !important;
    }

    [data-testid="stTextInput"] input::placeholder {
        color: #94a3b8 !important;
        -webkit-text-fill-color: #94a3b8 !important;
        opacity: 1 !important;
    }

    [data-testid="stTextInput"] button {
        background: #ffffff !important;
        color: #64748b !important;
        border: 0 !important;
        box-shadow: none !important;
    }

    [data-testid="stTextInput"] button svg {
        color: #64748b !important;
        fill: #64748b !important;
    }

    [data-testid="stFormSubmitButton"] button {
        min-height: 52px !important;
        background: linear-gradient(135deg, #f97316, #0f766e) !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        border: 0 !important;
        border-radius: 8px !important;
        font-weight: 850 !important;
        font-size: 1rem !important;
        box-shadow: 0 16px 28px rgba(249, 115, 22, 0.22) !important;
    }

    [data-testid="stFormSubmitButton"] button:hover {
        filter: brightness(1.03);
        transform: translateY(-1px);
        box-shadow: 0 18px 32px rgba(15, 118, 110, 0.25) !important;
    }

    [data-testid="stFormSubmitButton"] button p {
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        font-weight: 850 !important;
    }

    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploaderDropzone"] {
        background: rgba(255, 255, 255, 0.88) !important;
        border: 2px dashed rgba(15, 118, 110, 0.34) !important;
        border-radius: 8px !important;
        box-shadow: 0 16px 36px rgba(16, 42, 67, 0.07) !important;
    }

    [data-testid="stFileUploader"] *,
    [data-testid="stFileUploaderDropzone"] * {
        color: var(--ink) !important;
    }

    [data-testid="stFileUploader"] small,
    [data-testid="stFileUploaderDropzone"] small {
        color: #475569 !important;
    }

    [data-testid="stFileUploader"] button {
        background: #ffffff !important;
        color: var(--primary) !important;
        border: 1px solid rgba(15, 118, 110, 0.28) !important;
    }

    [data-testid="stAlert"],
    [data-testid="stAlert"] *,
    [data-testid="stNotification"],
    [data-testid="stNotification"] * {
        color: var(--ink) !important;
    }

    .uploadedFile {
        background: var(--soft);
        border: 2px dashed rgba(15, 118, 110, 0.34);
        border-radius: 8px;
        padding: 20px;
        transition: all 0.3s ease;
    }

    .uploadedFile:hover {
        border-color: var(--primary);
        background: #f0fdfa;
    }

    .skill-badge {
        display: inline-block;
        background: #e7f8f4;
        color: #115e59;
        padding: 7px 13px;
        border-radius: 999px;
        margin: 5px;
        font-weight: 750;
        font-size: 0.85rem;
        border: 1px solid #b7ebe0;
    }

    .skill-badge-missing {
        background: #fff1e7;
        color: #9a3412;
        border-color: #fed7aa;
    }

    .success-box {
        background: #ecfdf5;
        padding: 16px 20px;
        border-radius: 8px;
        color: #065f46;
        margin: 15px 0;
        font-weight: 750;
        border: 1px solid #a7f3d0;
    }

    .warning-box {
        background: #fffbeb;
        padding: 16px 20px;
        border-radius: 8px;
        color: #92400e;
        margin: 15px 0;
        font-weight: 750;
        border: 1px solid #fde68a;
    }

    .info-box {
        background: #eef9f6;
        padding: 16px 20px;
        border-radius: 8px;
        color: #115e59;
        margin: 15px 0;
        font-weight: 750;
        border: 1px solid #b7ebe0;
    }

    div[data-testid="stCheckbox"] {
        margin: 10px 0 14px;
        padding: 12px 14px;
        border-radius: 8px;
        background: #ffffff;
        border: 1px solid rgba(146, 64, 14, 0.22);
    }

    div[data-testid="stCheckbox"] label,
    div[data-testid="stCheckbox"] label *,
    div[data-testid="stCheckbox"] p {
        color: #102026 !important;
        -webkit-text-fill-color: #102026 !important;
        font-weight: 850 !important;
        opacity: 1 !important;
    }

    div[data-testid="stCheckbox"] [data-baseweb="checkbox"] {
        background-color: #ffffff !important;
        border-color: #0f766e !important;
    }

    .resume-history-row {
        padding: 16px 0 10px;
    }

    .resume-history-title {
        color: var(--ink);
        font-size: 1rem;
        font-weight: 800;
        line-height: 1.35;
        overflow-wrap: anywhere;
        margin-bottom: 5px;
    }

    .resume-history-meta {
        color: var(--muted);
        font-size: 0.86rem;
        font-weight: 650;
        line-height: 1.45;
    }

    .resume-history-pill {
        display: inline-flex;
        align-items: center;
        width: fit-content;
        padding: 7px 10px;
        border-radius: 999px;
        background: #f8fafc;
        border: 1px solid #dbeafe;
        color: #334155;
        font-size: 0.82rem;
        font-weight: 800;
        margin: 2px 8px 6px 0;
    }

    .stored-detail-panel {
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 22px;
        margin-top: 20px;
        box-shadow: 0 16px 34px rgba(16, 42, 67, 0.08);
    }

    .stProgress > div > div > div > div {
        background: var(--accent);
    }

    .streamlit-expanderHeader {
        background: var(--soft);
        border-radius: 8px;
        font-weight: 600;
        color: #374151;
        border: 1px solid var(--line);
    }

    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 900;
        color: var(--primary);
    }

    [data-testid="stMetricLabel"] {
        color: var(--muted);
        font-weight: 600;
    }

    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 0rem;
        max-width: 1280px;
    }

    .content-card {
        background: rgba(255, 255, 255, 0.92);
        border-radius: 8px;
        padding: 24px;
        border: 1px solid rgba(16, 42, 67, 0.08);
        box-shadow: 0 16px 34px rgba(16, 42, 67, 0.08);
        margin-bottom: 20px;
    }

    .stSelectbox > div > div {
        border-radius: 8px;
        border: 1px solid var(--line);
    }

    .sign-out-btn button {
        background: white !important;
        color: var(--navy) !important;
        border: 1px solid rgba(16, 42, 67, 0.10) !important;
        padding: 8px 20px !important;
        font-size: 0.9rem !important;
        box-shadow: 0 10px 20px rgba(16, 42, 67, 0.06) !important;
    }

    .sign-out-btn button:hover {
        background: var(--accent-soft) !important;
        color: #9a3412 !important;
    }

    @media (max-width: 768px) {
        .auth-page {
            margin-top: 12px;
            padding: 0;
        }

        .auth-brand-panel {
            min-height: auto;
            padding: 30px 24px;
            margin-bottom: 16px;
        }

        .auth-brand-title {
            font-size: 2.2rem;
        }

        .auth-feature-row {
            grid-template-columns: 1fr;
            margin-top: 24px;
        }

        [data-testid="column"]:has(.auth-form-anchor) {
            min-height: auto;
            padding: 28px 22px;
        }

        .login-container {
            margin-top: 0;
        }

        .dashboard-shell {
            padding: 0;
        }

        .dashboard-topbar {
            align-items: flex-start;
            flex-direction: column;
            margin-top: 0;
        }

        .dashboard-hero {
            min-height: auto;
            padding: 28px 22px;
        }

        .hero-title {
            font-size: 2.1rem;
        }

        .hero-copy {
            font-size: 0.95rem;
        }

        .stat-card {
            min-height: 110px;
            margin-bottom: 12px;
        }

        .stTabs [data-baseweb="tab-list"] {
            overflow-x: auto;
            justify-content: flex-start;
        }
    }
</style>
""", unsafe_allow_html=True)

def init_session_state():
    """Initialize session state variables"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'auth_session' not in st.session_state:
        st.session_state.auth_session = None
    if 'page' not in st.session_state:
        st.session_state.page = 'auth'
    if 'local_analyses' not in st.session_state:
        st.session_state.local_analyses = load_local_analyses()
    if 'show_uploaded_resume' not in st.session_state:
        st.session_state.show_uploaded_resume = False
    if 'current_upload_key' not in st.session_state:
        st.session_state.current_upload_key = None
    if 'current_upload_path' not in st.session_state:
        st.session_state.current_upload_path = None
    if 'current_upload_local_id' not in st.session_state:
        st.session_state.current_upload_local_id = None
    if 'current_upload_result' not in st.session_state:
        st.session_state.current_upload_result = None
    if 'current_resume_record' not in st.session_state:
        st.session_state.current_resume_record = None
    if 'selected_stored_resume_id' not in st.session_state:
        st.session_state.selected_stored_resume_id = None
    if st.session_state.get('parser_output_version') != PARSER_OUTPUT_VERSION:
        st.session_state.parser_output_version = PARSER_OUTPUT_VERSION
        st.session_state.current_upload_result = None
        st.session_state.current_resume_record = None
    if 'auth_service' not in st.session_state:
        try:
            init_supabase()
            st.session_state.auth_service = AuthService()
            st.session_state.resume_repo = ResumeRepository()
            st.session_state.skill_repo = SkillRepository()
        except Exception as e:
            st.error(f"Database connection error: {e}")
            st.stop()

    if not st.session_state.authenticated:
        restored = None
        cookie_session = read_auth_cookie()
        if cookie_session.get("access_token") and cookie_session.get("refresh_token"):
            restored = restore_auth_session_safely(
                st.session_state.auth_service,
                cookie_session
            )

        if restored and restored.get("success"):
            st.session_state.authenticated = True
            st.session_state.user = restored["user"]
            st.session_state.auth_session = restored.get("session") or cookie_session
            st.session_state.page = 'dashboard'
        else:
            current_user = st.session_state.auth_service.get_current_user()
            if current_user:
                st.session_state.authenticated = True
                st.session_state.user = current_user
                st.session_state.page = 'dashboard'

def show_auth_page():
    """Show modern authentication page"""
    st.markdown('<div class="auth-page">', unsafe_allow_html=True)

    brand_col, form_col = st.columns([1, 1], gap="small")

    with brand_col:
        st.markdown("""
        <div class="auth-brand-panel">
            <div>
                <div class="auth-kicker">AI resume intelligence</div>
                <h1 class="auth-brand-title">Resume analysis for your career dashboard.</h1>
                <p class="auth-brand-copy">
                    Upload a CV, review role matches, and track the skills found in each resume.
                </p>
            </div>
            <div class="auth-feature-row">
                <div class="auth-feature">
                    <strong>3x</strong>
                    <span>Top role matches from every analysis</span>
                </div>
                <div class="auth-feature">
                    <strong>100%</strong>
                    <span>Private history tied to your account</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with form_col:
        st.markdown('<span class="auth-form-anchor"></span>', unsafe_allow_html=True)
        st.markdown('<div class="auth-form-panel">', unsafe_allow_html=True)
        st.markdown("""
        <div class="login-container">
            <div class="login-header">
                <div class="auth-form-kicker">Secure career workspace</div>
                <div class="login-title">Welcome to Smart Career</div>
                <div class="login-subtitle">Continue your resume analysis and keep every skill-gap report in one place.</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        tab1, tab2 = st.tabs(["Sign In", "Sign Up"])
        
        with tab1:
            with st.form("signin_form", clear_on_submit=False):
                email = st.text_input("Email Address", placeholder="your.email@example.com", key="signin_email")
                password = st.text_input("Password", type="password", placeholder="Enter your password", key="signin_password")
                
                submit = st.form_submit_button("Sign In", width="stretch")
                
                if submit:
                    if email and password:
                        with st.spinner("Signing in..."):
                            result = st.session_state.auth_service.sign_in(email, password)
                            if result['success']:
                                st.session_state.authenticated = True
                                st.session_state.user = result['user']
                                st.session_state.auth_session = result.get('session')
                                st.session_state.page = 'dashboard'
                                write_auth_cookie(result.get('session'))
                                st.success("✅ " + result['message'])
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ " + result['message'])
                    else:
                        st.warning("⚠️ Please fill in all fields")

        with tab2:
            with st.form("signup_form", clear_on_submit=False):
                full_name = st.text_input("Full Name", placeholder="Your Name", key="signup_name")
                email = st.text_input("Email Address", placeholder="your.email@example.com", key="signup_email")
                password = st.text_input("Password", type="password", placeholder="Choose a strong password", key="signup_password")
                password_confirm = st.text_input("Confirm Password", type="password", placeholder="Re-enter your password", key="signup_confirm")
                
                submit = st.form_submit_button("Create Account", width="stretch")
                
                if submit:
                    if all([full_name, email, password, password_confirm]):
                        if password == password_confirm:
                            if len(password) >= 6:
                                with st.spinner("Creating account..."):
                                    result = st.session_state.auth_service.sign_up(email, password, full_name)
                                    if result['success']:
                                        st.success("✅ " + result['message'])
                                        st.info("💡 Please use the Sign In tab to access your account")
                                    else:
                                        st.error("❌ " + result['message'])
                            else:
                                st.error("❌ Password must be at least 6 characters")
                        else:
                            st.error("❌ Passwords do not match!")
                    else:
                        st.warning("⚠️ Please fill in all fields")

        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

def analysis_for_resume(resume: dict, analyses: list[dict]) -> dict:
    """Return full resume analysis, or the latest skill-gap analysis fallback."""
    analysis_result = resume.get("analysis_result") or {}
    if isinstance(analysis_result, str):
        try:
            analysis_result = json.loads(analysis_result)
        except Exception:
            analysis_result = {}

    if analysis_result:
        return {
            "role": analysis_result.get("chosen_role", "Not saved"),
            "score": analysis_result.get("match_score"),
            "source": "Full payload"
        }

    resume_id = resume.get("id")
    for analysis in analyses:
        if analysis.get("resume_id") == resume_id:
            return {
                "role": analysis.get("target_role", "Not saved"),
                "score": analysis.get("match_score"),
                "source": "Skill gap table"
            }

    return {
        "role": "Not saved",
        "score": None,
        "source": "Not saved"
    }


def build_stored_data_rows(resumes: list[dict], analyses: list[dict] | None = None) -> list[dict]:
    """Build compact rows for the dashboard stored-data preview."""
    analyses = analyses or []
    rows = []
    for resume in resumes:
        parsed_skills = resume.get("parsed_skills", [])
        if isinstance(parsed_skills, str):
            try:
                parsed_skills = json.loads(parsed_skills)
            except Exception:
                parsed_skills = []
        if not isinstance(parsed_skills, list):
            parsed_skills = []

        saved_analysis = analysis_for_resume(resume, analyses)
        match_score = saved_analysis.get("score")
        rows.append({
            "File": resume.get("filename", "Unknown File"),
            "Date": display_resume_date(resume),
            "Skills": len(parsed_skills),
            "Role": saved_analysis["role"],
            "Score": f"{match_score:.1f}%" if isinstance(match_score, (int, float)) else "Not saved",
            "Source": saved_analysis["source"]
        })

    return rows


def update_resume_analysis_safely(
    resume_repo: ResumeRepository,
    resume_id: str,
    user_id: str,
    result: dict
) -> None:
    """Save the full analysis payload when the repository/database supports it."""
    raw_text = result.get("parsed", {}).get("raw_text", "")
    parsed_data = result.get("parsed", {})

    if hasattr(resume_repo, "update_resume_analysis"):
        resume_repo.update_resume_analysis(
            resume_id=resume_id,
            user_id=user_id,
            raw_text=raw_text,
            parsed_data=parsed_data,
            analysis_result=result
        )
        return

    try:
        resume_repo.client.table("resumes").update({
            "raw_text": raw_text,
            "parsed_skills": parsed_data.get("skills", []),
            "parsed_education": parsed_data.get("education", []),
            "parsed_experience": parsed_data.get("experience", []),
            "analysis_result": json.loads(json.dumps(result))
        }).eq("id", resume_id).eq("user_id", user_id).execute()
    except Exception as e:
        if "analysis_result" not in str(e):
            print(f"Error updating resume analysis: {e}")


def save_resume_safely(
    resume_repo: ResumeRepository,
    user_id: str,
    filename: str,
    file_type: str,
    raw_text: str,
    parsed_data: dict,
    file_size: int,
    analysis_result: dict
) -> dict | None:
    """Save a resume with full analysis, falling back for older repository instances."""
    try:
        return resume_repo.save_resume(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            raw_text=raw_text,
            parsed_data=parsed_data,
            file_size=file_size,
            analysis_result=analysis_result
        )
    except TypeError as e:
        if "analysis_result" not in str(e):
            raise

        resume_record = resume_repo.save_resume(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            raw_text=raw_text,
            parsed_data=parsed_data,
            file_size=file_size
        )
        if resume_record:
            update_resume_analysis_safely(
                resume_repo=resume_repo,
                resume_id=resume_record["id"],
                user_id=user_id,
                result=analysis_result
            )
        return resume_record


def delete_user_resumes_safely(resume_repo: ResumeRepository, user_id: str) -> bool:
    """Delete all resumes even if Streamlit is holding an older repository instance."""
    if hasattr(resume_repo, "delete_user_resumes"):
        return resume_repo.delete_user_resumes(user_id)

    try:
        resume_repo.client.table("resumes").delete().eq(
            "user_id", user_id
        ).execute()
        return True
    except Exception as e:
        print(f"Error deleting user resumes: {e}")
        return False


def show_dashboard():
    """Show modern dashboard"""
    stats = st.session_state.resume_repo.get_resume_statistics(st.session_state.user.id)
    stored_resumes = st.session_state.resume_repo.get_user_resumes(st.session_state.user.id)
    stored_analyses = st.session_state.resume_repo.get_user_analyses(st.session_state.user.id, limit=100)
    local_analyses = [
        analysis for analysis in st.session_state.local_analyses
        if analysis.get("user_id") == st.session_state.user.id
    ]
    stored_analyses = [*stored_analyses, *local_analyses]
    if local_analyses:
        db_analysis_count = stats.get("total_analyses", 0)
        db_avg = stats.get("average_match_score", 0)
        db_score_total = db_avg * db_analysis_count
        local_score_total = sum(analysis.get("match_score", 0) for analysis in local_analyses)
        total_analyses = db_analysis_count + len(local_analyses)

        stats["total_analyses"] = total_analyses
        stats["average_match_score"] = round(
            (db_score_total + local_score_total) / total_analyses,
            2
        )

    user_name = st.session_state.user.email.split('@')[0].title() if st.session_state.user else "User"
    safe_user_name = html.escape(user_name)
    latest_analysis = stored_analyses[0] if stored_analyses else {}
    latest_role = html.escape(str(latest_analysis.get("target_role", "Upload a resume to begin")))
    latest_score = latest_analysis.get("match_score")
    latest_score_text = f"{latest_score:.1f}%" if isinstance(latest_score, (int, float)) else "No score yet"
    avg_match = stats.get("average_match_score", 0)

    st.markdown('<div class="dashboard-shell">', unsafe_allow_html=True)

    topbar_col, signout_col = st.columns([5, 1], vertical_alignment="center")
    with topbar_col:
        st.markdown("""
        <div class="dashboard-topbar">
            <div class="brand-lockup">
                <div class="brand-mark">RA</div>
                <div>
                    <div class="brand-title">Resume Analyzer</div>
                    <div class="brand-subtitle">Resume intelligence workspace</div>
                </div>
            </div>
            <div class="hero-pill">Private dashboard</div>
        </div>
        """, unsafe_allow_html=True)

    with signout_col:
        st.markdown('<div class="sign-out-btn">', unsafe_allow_html=True)
        if st.button("Sign Out", width="stretch"):
            st.session_state.auth_service.sign_out()
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.auth_session = None
            st.session_state.page = 'auth'
            clear_auth_cookie()
            time.sleep(0.2)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(f"""
    <div class="dashboard-hero">
        <div class="hero-kicker">Career command center</div>
        <div class="hero-title">Welcome back, {safe_user_name}.</div>
        <p class="hero-copy">
            Upload resumes, review match scores, and manage saved analysis results.
        </p>
        <div class="hero-strip">
            <span class="hero-pill">Latest focus: {latest_role}</span>
            <span class="hero-pill">Latest score: {latest_score_text}</span>
            <span class="hero-pill">Average match: {avg_match}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Total resumes</div>
            <div class="stat-number">{stats.get('total_resumes', 0)}</div>
            <div class="stat-subtext">Uploaded documents</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Analyses done</div>
            <div class="stat-number">{stats.get('total_analyses', 0)}</div>
            <div class="stat-subtext">Role checks saved</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Average match</div>
            <div class="stat-number">{stats.get('average_match_score', 0)}%</div>
            <div class="stat-subtext">Across analyses</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Unique skills</div>
            <div class="stat-number">{stats.get('unique_skills', 0)}</div>
            <div class="stat-subtext">Detected signals</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📤 Upload & Analyze", "📁 My Resumes", "📊 Analytics", "🗄️ Stored Data"])
    
    with tab1:
        show_upload_section()
    
    with tab2:
        show_my_resumes()
    
    with tab3:
        show_analytics()

    with tab4:
        show_stored_data(stored_resumes, stats, stored_analyses)

    st.markdown('</div>', unsafe_allow_html=True)

def show_upload_section():
    """Upload and analyze resume section"""
    st.markdown('<div class="section-header">📤 Upload Your Resume</div>', unsafe_allow_html=True)
    st.markdown("**Supports PDF and DOCX files. Scanned documents automatically processed with OCR.**")
    
    uploaded = st.file_uploader(
        "Choose your resume file",
        type=["pdf", "docx"],
        help="Upload your resume for AI-powered analysis",
        key="resume_upload"
    )
    
    if uploaded:
        safe_name = safe_upload_name(uploaded.name)
        upload_key = f"{uploaded.name}:{uploaded.size}:{uploaded.type}"
        uploaded_bytes = uploaded.getbuffer()

        if st.session_state.current_upload_key != upload_key:
            ts = time.strftime("%Y%m%d-%H%M%S")
            saved_path = UPLOADS_DIR / f"{ts}__{safe_name}"
            
            with saved_path.open("wb") as f:
                f.write(uploaded_bytes)

            st.session_state.current_upload_key = upload_key
            st.session_state.current_upload_path = str(saved_path)
            st.session_state.current_upload_local_id = f"local-{ts}"
            st.session_state.current_upload_result = None
            st.session_state.current_resume_record = None
            st.session_state.show_uploaded_resume = False
        else:
            saved_path = Path(st.session_state.current_upload_path)

        if st.button("View Resume", key=f"view_uploaded_resume_{safe_name}", width="stretch"):
            st.session_state.show_uploaded_resume = not st.session_state.show_uploaded_resume

        if st.session_state.show_uploaded_resume:
            show_resume_viewer(saved_path, uploaded.name, saved_path.suffix.lstrip("."))
        
        st.markdown('<div class="success-box">✅ Resume uploaded successfully! Analyzing now...</div>', unsafe_allow_html=True)

        roles_map = load_skill_dataset_from_db()
        if st.session_state.current_upload_result is None:
            with st.spinner("🔍 Analyzing your resume with AI..."):
                progress = st.progress(0)
                for i in range(100):
                    time.sleep(0.01)
                    progress.progress(i + 1)
                
                result = analyze_resume(str(saved_path))
                
                resume_record = save_resume_safely(
                    resume_repo=st.session_state.resume_repo,
                    user_id=st.session_state.user.id,
                    filename=uploaded.name,
                    file_type=saved_path.suffix.lstrip("."),
                    raw_text=result["parsed"].get("raw_text", ""),
                    parsed_data=result["parsed"],
                    file_size=uploaded.size,
                    analysis_result=result
                )

                st.session_state.current_upload_result = result
                st.session_state.current_resume_record = resume_record
        else:
            result = st.session_state.current_upload_result
            resume_record = st.session_state.current_resume_record
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown('<div class="section-header">🧩 Extracted Information</div>', unsafe_allow_html=True)
            
            skills = result["parsed"].get("skills", [])
            edu = clean_cv_display_items(result["parsed"].get("education", []), limit=3)
            exp = clean_cv_display_items(result["parsed"].get("experience", []), limit=3)
            
            st.markdown("**💡 Skills Found:**")
            if skills:
                skills_html = " ".join([f'<span class="skill-badge">{skill.title()}</span>' 
                                       for skill in sorted(skills)[:20]])
                st.markdown(skills_html, unsafe_allow_html=True)
                if len(skills) > 20:
                    st.info(f"+ {len(skills) - 20} more skills")
            else:
                st.markdown('<div class="warning-box">⚠️ No skills detected</div>', unsafe_allow_html=True)
            
            st.markdown("")
            st.markdown("**🎓 Education:**")
            if edu:
                for e in edu:
                    st.write(f"• {e}")
            else:
                st.write("—")
            
            st.markdown("")
            st.markdown("**💼 Experience:**")
            if exp:
                for e in exp:
                    st.write(f"• {e}")
            else:
                st.write("—")
        
        with col2:
            st.markdown('<div class="section-header"> Job Role Analysis</div>', unsafe_allow_html=True)
            
            preds = result.get("predictions", [])
            if preds:
                st.markdown("**Top Matching Roles:**")
                for role, score in preds[:3]:
                    st.markdown(f"**{role}** — {score:.1f}%")
                    st.progress(score / 100)
                    st.markdown("<br>", unsafe_allow_html=True)
                
                default_role = preds[0][0]
            else:
                default_role = list(roles_map.keys())[0] if roles_map else "Junior Data Scientist"
            
            st.markdown("<br>", unsafe_allow_html=True)
            chosen = st.selectbox(
                "🎯 Select Target Role for Detailed Analysis",
                options=list(roles_map.keys()),
                index=list(roles_map.keys()).index(default_role) if default_role in roles_map else 0
            )
            
            if chosen != result["chosen_role"]:
                with st.spinner("Recalculating..."):
                    result = analyze_resume(str(saved_path), chosen_role=chosen)
                    if resume_record:
                        update_resume_analysis_safely(
                            resume_repo=st.session_state.resume_repo,
                            resume_id=resume_record["id"],
                            user_id=st.session_state.user.id,
                            result=result
                        )
                        st.session_state.current_upload_result = result
            
            matched = result["gap"].get("matched", [])
            missing = result["gap"].get("missing", [])
            match_score = result.get('match_score', 0)
            
            st.markdown(f"<br>**Match Score: {match_score:.1f}%**", unsafe_allow_html=True)
            st.progress(match_score / 100)
            
            analysis_saved = None
            if resume_record:
                analysis_saved = st.session_state.resume_repo.save_skill_gap_analysis(
                    user_id=st.session_state.user.id,
                    resume_id=resume_record['id'],
                    target_role=chosen,
                    matched_skills=matched,
                    missing_skills=missing,
                    match_score=match_score
                )

            if not analysis_saved:
                st.session_state.local_analyses.append({
                    "user_id": st.session_state.user.id,
                    "resume_id": resume_record["id"] if resume_record else st.session_state.current_upload_local_id,
                    "target_role": chosen,
                    "matched_skills": matched,
                    "missing_skills": missing,
                    "match_score": match_score,
                    "analysis_date": datetime.now().isoformat()
                })
                persist_local_analyses(st.session_state.local_analyses)
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="section-header">✅ Matched Skills</div>', unsafe_allow_html=True)
            if matched:
                matched_html = " ".join([f'<span class="skill-badge">{skill.title()}</span>' 
                                        for skill in sorted(matched)])
                st.markdown(matched_html, unsafe_allow_html=True)
            else:
                st.write("—")
        
        with col2:
            st.markdown('<div class="section-header">❌ Skills to Learn</div>', unsafe_allow_html=True)
            if missing:
                missing_html = " ".join([f'<span class="skill-badge skill-badge-missing">{skill.title()}</span>' 
                                        for skill in sorted(missing)])
                st.markdown(missing_html, unsafe_allow_html=True)
            else:
                st.markdown('<div class="success-box">🎉 Perfect match! No skills missing!</div>', unsafe_allow_html=True)
        
def show_my_resumes():
    """Show user's uploaded resumes"""
    st.markdown('<div class="section-header">📁 Your Resume History</div>', unsafe_allow_html=True)
    
    resumes = st.session_state.resume_repo.get_user_resumes(st.session_state.user.id)
    
    if not resumes:
        st.markdown(
            '<div class="info-box">📭 No resumes yet. Upload your first resume in the "Upload & Analyze" tab!</div>',
            unsafe_allow_html=True
        )
        return

    st.markdown('<div class="warning-box">Remove every saved resume from your account and start fresh from the next upload.</div>', unsafe_allow_html=True)
    confirm_clear = st.checkbox(
        "I understand this will delete all my saved resumes",
        key="confirm_clear_resume_history"
    )
    if st.button(
        "Clear All Resume History",
        key="clear_all_resume_history",
        disabled=not confirm_clear,
        width="stretch"
    ):
        if delete_user_resumes_safely(
            st.session_state.resume_repo,
            st.session_state.user.id
        ):
            st.session_state.local_analyses = [
                analysis for analysis in st.session_state.local_analyses
                if analysis.get("user_id") != st.session_state.user.id
            ]
            persist_local_analyses(st.session_state.local_analyses)
            st.session_state.selected_stored_resume_id = None
            st.success("All saved resumes were deleted. New uploads will be stored from now on.")
            st.rerun()
        else:
            st.error("Could not clear the resume history. Please try again while signed in.")
    
    for resume in resumes:
        # ✅ Safe filename
        filename = resume.get("filename", "Unknown File")
        
        # ✅ Safe upload date handling
        display_date = display_resume_date(resume)
        
        with st.expander(f"📄 {filename} — {display_date}"):
            
            col1, col2, col3 = st.columns(3)
            
            # ✅ Safe file size
            file_size = resume.get("file_size", 0) or 0
            with col1:
                st.metric("📦 File Size", f"{file_size / 1024:.1f} KB")
            
            # ✅ Safe parsed skills
            parsed_skills = resume.get("parsed_skills", [])
            
            if isinstance(parsed_skills, str):
                try:
                    parsed_skills = json.loads(parsed_skills)
                except Exception:
                    parsed_skills = []
            
            if not isinstance(parsed_skills, list):
                parsed_skills = []
            
            with col2:
                st.metric("💡 Skills", len(parsed_skills))
            
            with col3:
                file_type = resume.get("file_type", "unknown")
                st.metric("📝 Type", file_type.upper())
            
            # ✅ Show skills safely
            if parsed_skills:
                st.markdown("<br>**Skills:**", unsafe_allow_html=True)
                skills_html = " ".join(
                    [f'<span class="skill-badge">{skill}</span>' for skill in parsed_skills[:15]]
                )
                st.markdown(skills_html, unsafe_allow_html=True)
            
            # ✅ Safe delete button
            resume_id = resume.get("id")
            if resume_id:
                if st.button(
                    f"🗑️ Delete Resume",
                    key=f"del_{resume_id}",
                    width="stretch"
                ):
                    st.session_state.resume_repo.delete_resume(
                        resume_id,
                        st.session_state.user.id
                    )
                    st.success("✅ Resume deleted!")
                    st.rerun()


def show_analytics():
    """Show analytics and visualizations"""
    st.markdown('<div class="section-header">📊 Your Analytics Dashboard</div>', unsafe_allow_html=True)
    
    analyses = st.session_state.resume_repo.get_user_analyses(st.session_state.user.id, limit=50)
    local_analyses = [
        analysis for analysis in st.session_state.local_analyses
        if analysis.get("user_id") == st.session_state.user.id
    ]
    if local_analyses:
        analyses = [*analyses, *local_analyses]
    
    if not analyses:
        st.markdown('<div class="info-box">📊 No analyses yet. Complete your first resume analysis to see insights!</div>', unsafe_allow_html=True)
        return
    
    df = pd.DataFrame(analyses)
    df['analysis_date'] = pd.to_datetime(df['analysis_date'])
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📈 Match Score Progress**")
        fig = px.line(
            df,
            x='analysis_date',
            y='match_score',
            title='Your Improvement Over Time',
            labels={'match_score': 'Match Score (%)', 'analysis_date': 'Date'}
        )
        fig.update_traces(line_color='#2563eb', line_width=3)
        fig.update_layout(
            plot_bgcolor='white',
            paper_bgcolor='white',
            font=dict(family="Inter")
        )
        st.plotly_chart(fig, width="stretch")
    
    with col2:
        st.markdown("**🎯 Roles Analyzed**")
        role_counts = df['target_role'].value_counts()
        fig = px.pie(
            values=role_counts.values,
            names=role_counts.index,
            title='Distribution of Analyzed Roles'
        )
        fig.update_traces(marker=dict(colors=['#2563eb', '#10b981', '#f59e0b', '#64748b']))
        fig.update_layout(
            paper_bgcolor='white',
            font=dict(family="Inter")
        )
        st.plotly_chart(fig, width="stretch")
    
def show_stored_data(resumes: list[dict], stats: dict, analyses: list[dict]):
    """Show database-backed resume analysis data."""
    st.markdown('<div class="section-header">🗄️ Stored Resume Data</div>', unsafe_allow_html=True)

    if not resumes:
        st.markdown(
            '<div class="info-box">No stored resume data yet. Upload and analyze a CV to save parsed data here.</div>',
            unsafe_allow_html=True
        )
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Stored Records", stats.get("stored_data_count", 0))
    with col2:
        st.metric("Saved Analyses", max(stats.get("stored_analysis_count", 0), len(analyses)))
    with col3:
        st.metric("Unique Skills", stats.get("unique_skills", 0))

    def parsed_skills_for(resume: dict) -> list:
        parsed_skills = resume.get("parsed_skills", [])
        if isinstance(parsed_skills, str):
            try:
                parsed_skills = json.loads(parsed_skills)
            except Exception:
                parsed_skills = []
        return parsed_skills if isinstance(parsed_skills, list) else []

    def resume_key(resume: dict, index: int) -> str:
        return str(resume.get("id") or f"stored-resume-{index}")

    st.markdown("<br>**Uploaded Resumes**", unsafe_allow_html=True)

    selected_resume = None
    for index, resume in enumerate(resumes):
        key = resume_key(resume, index)
        if st.session_state.selected_stored_resume_id == key:
            selected_resume = resume

        filename = resume.get("filename", "Unknown File")
        display_date = display_resume_date(resume)
        file_type = str(resume.get("file_type", "unknown")).upper()
        file_size = resume.get("file_size", 0) or 0
        parsed_skills = parsed_skills_for(resume)
        saved_analysis = analysis_for_resume(resume, analyses)
        score = saved_analysis["score"]
        score_text = f"{score:.1f}%" if isinstance(score, (int, float)) else "Not saved"
        role = saved_analysis["role"]

        with st.container(border=True):
            row_col, status_col, action_col = st.columns([5.5, 2.2, 1.4], vertical_alignment="center")
            with row_col:
                st.markdown(
                    f"""
                    <div class="resume-history-row">
                        <div class="resume-history-title">{html.escape(str(filename))}</div>
                        <div class="resume-history-meta">
                            Uploaded {html.escape(display_date)} · {html.escape(file_type)}
                            · {file_size / 1024:.1f} KB
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with status_col:
                st.markdown(
                    f"""
                    <span class="resume-history-pill">{len(parsed_skills)} skills</span>
                    <span class="resume-history-pill">{html.escape(score_text)}</span>
                    <div class="resume-history-meta">{html.escape(str(role))}</div>
                    """,
                    unsafe_allow_html=True
                )
            with action_col:
                if st.button("View Data", key=f"view_stored_resume_{key}", width="stretch"):
                    st.session_state.selected_stored_resume_id = key
                    selected_resume = resume

    if not selected_resume:
        return

    filename = selected_resume.get("filename", "Unknown File")
    parsed_skills = parsed_skills_for(selected_resume)
    saved_analysis = analysis_for_resume(selected_resume, analyses)
    role = saved_analysis["role"]
    score = saved_analysis["score"]
    score_text = f"{score:.1f}%" if isinstance(score, (int, float)) else "Not saved"

    st.markdown(
        f"""
        <div class="stored-detail-panel">
            <div class="resume-history-meta">Viewing data for</div>
            <div class="resume-history-title">{html.escape(str(filename))}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    detail_col1, detail_col2, detail_col3, detail_col4 = st.columns(4)
    with detail_col1:
        st.metric("Saved Skills", len(parsed_skills))
    with detail_col2:
        st.metric("Role", role)
    with detail_col3:
        st.metric("Match", score_text)
    with detail_col4:
        st.metric("Source", saved_analysis["source"])

    if parsed_skills:
        st.markdown("**Skills**")
        skills_html = " ".join(
            f'<span class="skill-badge">{html.escape(str(skill))}</span>'
            for skill in parsed_skills[:30]
        )
        st.markdown(skills_html, unsafe_allow_html=True)

    raw_text = selected_resume.get("raw_text") or ""
    if raw_text:
        st.text_area("Extracted Text Preview", raw_text[:1200], height=180, disabled=True)

# ============================================
# 🌐 CUSTOM FOOTER SECTION (Modern Gradient)
# ============================================
def show_footer():
    st.markdown("""
    <style>
        .footer {
            position: relative;
            bottom: 0;
            width: 100%;
            text-align: center;
            padding: 25px 0;
            margin-top: 60px;
            background: #ffffff;
            border-top: 1px solid #e5e7eb;
            color: #475569;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            box-shadow: 0 -5px 20px rgba(0,0,0,0.1);
        }
        .footer a {
            color: #2563eb;
            text-decoration: none;
            font-weight: 600;
            margin: 0 12px;
            transition: color 0.3s ease;
        }
        .footer a:hover {
            color: #1d4ed8;
        }
        .footer p {
            margin: 5px 0 0 0;
            font-size: 0.95rem;
            opacity: 0.9;
        }
        .social-icons {
            margin-top: 10px;
        }
        .social-icons a {
            margin: 0 8px;
            display: inline-block;
            font-size: 1.2rem;
        }
    </style>

    <div class="footer">
        <p> Built by <strong>Binuja Subedi</strong></p>
        <div class="social-icons">
           <a href="https://github.com/binujasubedi" class="footer-link">GitHub</a>
        </div>
        <p>© 2026 Smart Career — All Rights Reserved.</p>
    </div>
    """, unsafe_allow_html=True)

def main():
    """Main application logic"""
    init_session_state()

    if not st.session_state.authenticated:
        show_auth_page()
    else:
        show_dashboard()

if __name__ == "__main__":
    main()

show_footer()
