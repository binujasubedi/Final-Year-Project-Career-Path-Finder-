from __future__ import annotations
from pathlib import Path
import base64
import html
import sys
import time
import streamlit as st
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


def safe_upload_name(filename: str) -> str:
    return Path(filename).name.replace(" ", "_")


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
    if not ANALYSES_CACHE_PATH.exists():
        return []
    try:
        return json.loads(ANALYSES_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def persist_local_analyses(analyses: list[dict]) -> None:
    try:
        ANALYSES_CACHE_PATH.write_text(
            json.dumps(analyses, ensure_ascii=True, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass

st.set_page_config(
    page_title="Smart Career",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Fresh, simple UI theme
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    :root {
        --primary: #2563eb;
        --primary-dark: #1d4ed8;
        --accent: #10b981;
        --danger: #ef4444;
        --warning: #f59e0b;
        --ink: #111827;
        --muted: #6b7280;
        --line: #e5e7eb;
        --panel: #ffffff;
        --soft: #f8fafc;
    }

    * {
        font-family: 'Inter', sans-serif;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    .stApp {
        background: linear-gradient(180deg, #f8fafc 0%, #eef6ff 100%);
        color: var(--ink);
    }

    .login-container {
        max-width: 460px;
        margin: 48px auto 24px;
        background: var(--panel);
        border-radius: 8px;
        padding: 36px;
        box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
        border: 1px solid var(--line);
    }

    .login-header {
        text-align: center;
        margin-bottom: 40px;
    }

    .login-title {
        font-size: 2rem;
        font-weight: 700;
        color: var(--ink);
        margin-bottom: 12px;
        letter-spacing: 0;
    }

    .login-subtitle {
        color: var(--muted);
        font-size: 1rem;
        font-weight: 400;
        line-height: 1.5;
    }

    .dashboard-container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 0 24px;
    }

    .welcome-banner {
        background: linear-gradient(135deg, var(--primary) 0%, #0f766e 100%);
        padding: 30px;
        border-radius: 8px;
        color: white;
        margin-bottom: 32px;
        box-shadow: 0 14px 30px rgba(37, 99, 235, 0.16);
    }

    .welcome-title {
        font-size: 1.65rem;
        font-weight: 600;
        margin: 0 0 8px 0;
        color: white;
    }

    .welcome-subtitle {
        font-size: 1rem;
        opacity: 0.9;
        margin: 0;
        color: white;
    }

    .stat-card {
        background: var(--panel);
        padding: 24px;
        border-radius: 8px;
        border: 1px solid var(--line);
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
        transition: all 0.3s ease;
        text-align: center;
    }

    .stat-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
        border-color: #bfdbfe;
    }

    .stat-number {
        font-size: 2.25rem;
        font-weight: 700;
        color: var(--primary);
        margin: 12px 0;
    }

    .stat-label {
        font-size: 0.8rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
    }

    .section-header {
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--ink);
        margin: 40px 0 24px 0;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--line);
    }

    .stButton > button,
    .stDownloadButton > button {
        background: var(--primary) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 8px;
        padding: 14px 28px;
        font-weight: 700;
        font-size: 0.95rem;
        transition: all 0.3s ease;
        width: 100%;
        box-shadow: 0 10px 20px rgba(37, 99, 235, 0.18);
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover {
        transform: translateY(-2px);
        background: var(--primary-dark) !important;
        color: #ffffff !important;
        box-shadow: 0 14px 24px rgba(37, 99, 235, 0.22);
    }

    .stButton > button *,
    .stDownloadButton > button * {
        color: #ffffff !important;
    }

    .secondary-btn button,
    .secondary-btn button * {
        background: white !important;
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
        gap: 6px;
        background: #eaf2ff;
        padding: 6px;
        border-radius: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 48px;
        background: transparent;
        border-radius: 6px;
        padding: 12px 20px;
        font-weight: 500;
        color: #475569;
        border: none;
        transition: all 0.3s ease;
    }

    .stTabs [aria-selected="true"] {
        background: white;
        color: var(--primary);
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
    }

    .stTextInput > div > div > input {
        border-radius: 8px;
        border: 1px solid var(--line);
        padding: 14px 16px;
        font-size: 0.95rem;
        transition: all 0.3s ease;
    }

    .stTextInput > div > div > input:focus {
        border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
    }

    /* Streamlit controls: force readable text on the light app theme */
    .stMarkdown,
    .stMarkdown p,
    .stMarkdown li,
    label,
    [data-testid="stWidgetLabel"],
    [data-testid="stFileUploader"] {
        color: var(--ink);
    }

    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploaderDropzone"] {
        background: #ffffff !important;
        border: 2px dashed #bfdbfe !important;
        border-radius: 8px !important;
    }

    [data-testid="stFileUploader"] section *,
    [data-testid="stFileUploaderDropzone"] * {
        color: var(--ink) !important;
    }

    [data-testid="stFileUploader"] small,
    [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] {
        color: #475569 !important;
    }

    [data-testid="stFileUploader"] button {
        background: #ffffff !important;
        color: var(--primary) !important;
        border: 1px solid #bfdbfe !important;
    }

    [data-testid="stFileUploaderFile"],
    [data-testid="stFileUploaderFileData"] {
        background: #ffffff !important;
        color: var(--ink) !important;
    }

    [data-testid="stFileUploaderFile"] *,
    [data-testid="stFileUploaderFileData"] * {
        color: var(--ink) !important;
    }

    [data-testid="stFileUploaderFile"] svg,
    [data-testid="stFileUploaderDeleteBtn"] svg {
        color: #475569 !important;
        fill: none !important;
        stroke: currentColor !important;
    }

    [data-testid="stAlert"],
    [data-testid="stAlert"] *,
    [data-testid="stNotification"],
    [data-testid="stNotification"] * {
        color: var(--ink) !important;
    }

    input,
    textarea,
    [data-baseweb="select"] *,
    [data-baseweb="popover"] * {
        color: var(--ink) !important;
    }

    .uploadedFile {
        background: var(--soft);
        border: 2px dashed #bfdbfe;
        border-radius: 8px;
        padding: 24px;
        transition: all 0.3s ease;
    }

    .uploadedFile:hover {
        border-color: var(--primary);
        background: #eff6ff;
    }

    .skill-badge {
        display: inline-block;
        background: #dbeafe;
        color: #1e40af;
        padding: 7px 13px;
        border-radius: 999px;
        margin: 6px;
        font-weight: 600;
        font-size: 0.8rem;
        border: 1px solid #bfdbfe;
    }

    .skill-badge-missing {
        background: #fee2e2;
        color: #991b1b;
        border-color: #fecaca;
    }

    .success-box {
        background: #ecfdf5;
        padding: 20px 24px;
        border-radius: 8px;
        color: #065f46;
        margin: 20px 0;
        font-weight: 500;
        border: 1px solid #a7f3d0;
    }

    .warning-box {
        background: #fffbeb;
        padding: 20px 24px;
        border-radius: 8px;
        color: #92400e;
        margin: 20px 0;
        font-weight: 500;
        border: 1px solid #fde68a;
    }

    .info-box {
        background: #eff6ff;
        padding: 20px 24px;
        border-radius: 8px;
        color: #1e3a8a;
        margin: 20px 0;
        font-weight: 500;
        border: 1px solid #bfdbfe;
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
        margin-bottom: 8px;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 700;
        color: var(--primary);
    }

    [data-testid="stMetricLabel"] {
        color: var(--muted);
        font-weight: 600;
    }

    .block-container {
        padding-top: 2rem;
        padding-bottom: 0rem;
    }

    .content-card {
        background: var(--panel);
        border-radius: 8px;
        padding: 24px;
        border: 1px solid var(--line);
        margin-bottom: 20px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
    }

    .stSelectbox > div > div {
        border-radius: 8px;
        border: 1px solid var(--line);
    }

    .dataframe {
        border: 1px solid var(--line) !important;
        border-radius: 8px !important;
        overflow: hidden !important;
    }

    @media (max-width: 768px) {
        .login-container {
            padding: 28px 22px;
            margin-top: 24px;
        }

        .dashboard-container {
            padding: 0 8px;
        }

        .welcome-banner {
            padding: 24px;
        }

        .stat-card {
            margin-bottom: 12px;
        }
    }

    /* Custom spacing */
    .spacing-sm { margin-bottom: 16px; }
    .spacing-md { margin-bottom: 24px; }
    .spacing-lg { margin-bottom: 32px; }
</style>
""", unsafe_allow_html=True)

def init_session_state():
    """Initialize session state variables"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user' not in st.session_state:
        st.session_state.user = None
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
    if 'auth_service' not in st.session_state:
        try:
            init_supabase()
            st.session_state.auth_service = AuthService()
            st.session_state.resume_repo = ResumeRepository()
            st.session_state.skill_repo = SkillRepository()
        except Exception as e:
            st.error(f"Database connection error: {e}")
            st.stop()

def show_auth_page():
    """Show premium authentication page"""
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div class="login-container">
            <div class="login-header">
                <div class="login-title">Smart Career</div>
                <div class="login-subtitle">Advanced Resume Analysis & Skill Gap Detection</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        tab1, tab2 = st.tabs(["🔐 Sign In", "📝 Sign Up"])
        
        with tab1:
            st.markdown('<div class="spacing-md"></div>', unsafe_allow_html=True)
            with st.form("signin_form", clear_on_submit=False):
                email = st.text_input("Email Address", placeholder="your.email@example.com", key="signin_email")
                password = st.text_input("Password", type="password", placeholder="Enter your password", key="signin_password")
                
                st.markdown('<div class="spacing-md"></div>', unsafe_allow_html=True)
                submit = st.form_submit_button("Sign In", width="stretch")

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown('<div style="font-size: 0.85rem; color: #666;">Forgot password?</div>', unsafe_allow_html=True)
                with col2:
                    st.markdown('<div style="font-size: 0.85rem; color: #666; text-align: right;">New here? Create account</div>', unsafe_allow_html=True)
                
                if submit:
                    if email and password:
                        with st.spinner("Signing in..."):
                            result = st.session_state.auth_service.sign_in(email, password)
                            if result['success']:
                                st.session_state.authenticated = True
                                st.session_state.user = result['user']
                                st.session_state.page = 'dashboard'
                                st.success("✅Success!" + result['message'])
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌Error: " + result['message'])
                    else:
                        st.warning("Please fill in all fields")
        
        with tab2:
            st.markdown('<div class="spacing-md"></div>', unsafe_allow_html=True)
            with st.form("signup_form", clear_on_submit=False):
                full_name = st.text_input("Full Name", placeholder="Enter Your Name", key="signup_name")
                email = st.text_input("Email Address", placeholder="your.email@example.com", key="signup_email")
                password = st.text_input("🔒 Password", type="password", placeholder="Choose a strong password", key="signup_password")
                password_confirm = st.text_input("🔒 Confirm Password", type="password", placeholder="Re-enter your password", key="signup_confirm")
                
                st.markdown('<div class="spacing-md"></div>', unsafe_allow_html=True)
                submit = st.form_submit_button("Create Account", width="stretch")
                
                if submit:
                    if all([full_name, email, password, password_confirm]):
                        if password == password_confirm:
                            if len(password) >= 6:
                                with st.spinner("Creating account..."):
                                    result = st.session_state.auth_service.sign_up(email, password, full_name)
                                    if result['success']:
                                        st.success("SUCCESS: " + result['message'])
                                        st.info(" Please use the Sign In tab to access your account")
                                    else:
                                        st.error("ERROR: " + result['message'])
                            else:
                                st.error("❌ Password must be at least 6 characters")
                        else:
                            st.error("❌ Passwords do not match!")
                    else:
                        st.warning("⚠️ Please fill in all fields")

def show_dashboard():
    """Show premium dashboard"""
    # Header with sign out
    col1, col2 = st.columns([4, 1])
    with col1:
        user_name = st.session_state.user.email.split('@')[0].title() if st.session_state.user else "User"
        st.markdown(f"""
        <div class="welcome-banner">
            <div class="welcome-title"> Welcome back, {user_name}!</div>
            <div class="welcome-subtitle">Track your resume analysis, match scores, and skill development journey</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown('<div class="spacing-md"></div>', unsafe_allow_html=True)
        st.markdown('<div class="secondary-btn">', unsafe_allow_html=True)
        if st.button(" Sign Out", width="stretch"):
            st.session_state.auth_service.sign_out()
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.page = 'auth'
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Statistics Cards
    stats = st.session_state.resume_repo.get_resume_statistics(st.session_state.user.id)
    local_analyses = [
        analysis for analysis in st.session_state.local_analyses
        if analysis.get("user_id") == st.session_state.user.id
    ]
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
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">📁 Total Resumes</div>
            <div class="stat-number">{stats['total_resumes']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">📊 Analyses Done</div>
            <div class="stat-number">{stats['total_analyses']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label"> Avg Match</div>
            <div class="stat-number">{stats['average_match_score']}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label"> Unique Skills</div>
            <div class="stat-number">{stats['unique_skills']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown('<div class="spacing-lg"></div>', unsafe_allow_html=True)
    
    # Main content tabs
    tab1, tab2, tab3 = st.tabs(["📤 Upload & Analyze", "📁 My Resumes", "📊 Analytics"])
    
    with tab1:
        show_upload_section()
    
    with tab2:
        show_my_resumes()
    
    with tab3:
        show_analytics()

def show_upload_section():
    """Upload and analyze resume section"""
    st.markdown('<div class="section-header"> Upload Your Resume</div>', unsafe_allow_html=True)
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
                
                resume_record = st.session_state.resume_repo.save_resume(
                    user_id=st.session_state.user.id,
                    filename=uploaded.name,
                    file_type=saved_path.suffix.lstrip("."),
                    raw_text="",
                    parsed_data=result["parsed"],
                    file_size=uploaded.size
                )

                st.session_state.current_upload_result = result
                st.session_state.current_resume_record = resume_record
        else:
            result = st.session_state.current_upload_result
            resume_record = st.session_state.current_resume_record
        
        st.markdown('<div class="spacing-lg"></div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown('<div class="section-header">🧩 Extracted Information</div>', unsafe_allow_html=True)
            
            skills = result["parsed"].get("skills", [])
            edu = result["parsed"].get("education", [])
            exp = result["parsed"].get("experience", [])
            
            st.markdown("** Skills Found:**")
            if skills:
                skills_html = " ".join([f'<span class="skill-badge">{skill.title()}</span>' 
                                       for skill in sorted(skills)[:20]])
                st.markdown(skills_html, unsafe_allow_html=True)
                if len(skills) > 20:
                    st.info(f"+ {len(skills) - 20} more skills")
            else:
                st.markdown('<div class="warning-box">⚠️ No skills detected</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="spacing-sm"></div>', unsafe_allow_html=True)
            st.markdown("**🎓 Education:**")
            if edu:
                for e in edu[:3]:
                    st.write(f"• {e}")
            else:
                st.write("—")
            
            st.markdown('<div class="spacing-sm"></div>', unsafe_allow_html=True)
            st.markdown("**💼 Experience:**")
            if exp:
                for e in exp[:3]:
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
                    st.markdown('<div class="spacing-sm"></div>', unsafe_allow_html=True)
                
                default_role = preds[0][0]
            else:
                default_role = list(roles_map.keys())[0] if roles_map else "Junior Data Scientist"
            
            st.markdown('<div class="spacing-md"></div>', unsafe_allow_html=True)
            chosen = st.selectbox(
                " Select Target Role for Detailed Analysis",
                options=list(roles_map.keys()),
                index=list(roles_map.keys()).index(default_role) if default_role in roles_map else 0
            )
            
            if chosen != result["chosen_role"]:
                with st.spinner("Recalculating..."):
                    result = analyze_resume(str(saved_path), chosen_role=chosen)
            
            matched = result["gap"].get("matched", [])
            missing = result["gap"].get("missing", [])
            match_score = result.get('match_score', 0)
            
            st.markdown(f'<div class="spacing-md"></div><div style="font-size: 1.1rem; font-weight: 600; color: #111827;">Match Score: {match_score:.1f}%</div>', unsafe_allow_html=True)
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
        
        st.markdown('<div class="spacing-lg"></div>', unsafe_allow_html=True)
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
        st.markdown('<div class="info-box"> No resumes yet. Upload your first resume in the "Upload & Analyze" tab!</div>', unsafe_allow_html=True)
        return
    
    for resume in resumes:
        with st.expander(f"📄 {resume['filename']} — {resume['upload_date'][:10]}"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric(" File Size", f"{resume['file_size'] / 1024:.1f} KB")
            
            with col2:
                skills_count = len(json.loads(resume['parsed_skills'])) if isinstance(resume['parsed_skills'], str) else len(resume['parsed_skills'])
                st.metric(" Skills", skills_count)
            
            with col3:
                st.metric("📝 Type", resume['file_type'].upper())
            
            skills = json.loads(resume['parsed_skills']) if isinstance(resume['parsed_skills'], str) else resume['parsed_skills']
            if skills:
                st.markdown('<div class="spacing-sm"></div>', unsafe_allow_html=True)
                st.markdown("**Skills:**")
                skills_html = " ".join([f'<span class="skill-badge">{skill}</span>' for skill in skills[:15]])
                st.markdown(skills_html, unsafe_allow_html=True)
            
            st.markdown('<div class="spacing-sm"></div>', unsafe_allow_html=True)
            if st.button(f"🗑️ Delete Resume", key=f"del_{resume['id']}", width="stretch"):
                st.session_state.resume_repo.delete_resume(resume['id'], st.session_state.user.id)
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
    if "target_role" not in df.columns:
        df["target_role"] = "Unknown Role"
    else:
        df["target_role"] = df["target_role"].fillna("Unknown Role")
    df['analysis_date'] = pd.to_datetime(df['analysis_date'])
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📈 Match Score Progress**")
        fig = px.line(
            df,
            x='analysis_date',
            y='match_score',
            labels={'match_score': 'Match Score (%)', 'analysis_date': 'Date'}
        )
        fig.update_traces(line_color='#2563eb', line_width=3)
        fig.update_layout(
            plot_bgcolor='white',
            paper_bgcolor='white',
            font=dict(family="Inter"),
            showlegend=False
        )
        st.plotly_chart(fig, width="stretch")
    
    with col2:
        st.markdown("** Roles Analyzed**")
        role_counts = df['target_role'].value_counts()
        fig = px.pie(
            values=role_counts.values,
            names=role_counts.index,
        )
        fig.update_traces(marker=dict(colors=['#2563eb', '#10b981', '#f59e0b', '#64748b']))
        fig.update_layout(
            paper_bgcolor='white',
            font=dict(family="Inter"),
            showlegend=True
        )
        st.plotly_chart(fig, width="stretch")
    
    st.markdown('<div class="spacing-md"></div>', unsafe_allow_html=True)
    st.markdown("**🏆 Top Performing Analyses**")
    top_analyses = df.nlargest(5, 'match_score')[['target_role', 'match_score', 'analysis_date']]
    top_analyses['analysis_date'] = top_analyses['analysis_date'].dt.strftime('%Y-%m-%d')
    top_analyses.columns = ['Role', 'Match Score (%)', 'Date']
    st.dataframe(top_analyses, width="stretch", hide_index=True)

def show_footer():
    """Show premium footer"""
    st.markdown("""
    <style>
        .footer {
            background: white;
            padding: 40px 0;
            margin-top: 80px;
            border-top: 1px solid #e5e7eb;
        }
        .footer-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 24px;
        }
        .footer-grid {
            display: grid;
            grid-template-columns: 2fr 1fr 1fr 1fr;
            gap: 40px;
            margin-bottom: 40px;
        }
        .footer-section h4 {
            font-weight: 600;
            color: #111827;
            margin-bottom: 16px;
            font-size: 1rem;
        }
        .footer-link {
            display: block;
            color: #6b7280;
            text-decoration: none;
            margin-bottom: 8px;
            font-size: 0.9rem;
            transition: color 0.3s ease;
        }
        .footer-link:hover {
            color: #2563eb;
        }
        .footer-bottom {
            text-align: center;
            padding-top: 24px;
            border-top: 1px solid #f0f0f0;
            color: #6b7280;
            font-size: 0.85rem;
        }
    </style>

    <div class="footer">
        <div class="footer-content">
            <div class="footer-grid">
                <div class="footer-section">
                    <h4>Smart Career</h4>
                    <p style="color: #6b7280; font-size: 0.9rem; line-height: 1.5;">
                        Advanced AI-powered resume analysis and skill gap detection to help you land your dream job.
                    </p>
                </div>
                <div class="footer-section">
                    <h4>Services</h4>
                    <a href="#" class="footer-link">Resume Analysis</a>
                    <a href="#" class="footer-link">Skill Gap Detection</a>
                    <a href="#" class="footer-link">Career Planning</a>
                </div>
                <div class="footer-section">
                    <h4>Company</h4>
                    <a href="#" class="footer-link">About</a>
                    <a href="#" class="footer-link">Privacy Policy</a>
                    <a href="#" class="footer-link">Terms of Service</a>
                </div>
                <div class="footer-section">
                    <h4>Connect</h4>
                    <a href="https://github.com/binujasubedi" class="footer-link">GitHub</a>
            </div>
            <div class="footer-bottom">
                © 2026 Smart Career. Built by Binuja Subedi. All rights reserved.
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def main():
    """Main application logic"""
    init_session_state()

    if not st.session_state.authenticated:
        show_auth_page()
    else:
        show_dashboard()
    
    show_footer()

if __name__ == "__main__":
    main()
