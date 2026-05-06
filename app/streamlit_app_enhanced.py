from __future__ import annotations
from pathlib import Path
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
        --primary: #2563eb;
        --primary-dark: #1d4ed8;
        --accent: #10b981;
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
        text-align: center;
        margin-bottom: 30px;
    }

    .login-title {
        font-size: 2rem;
        font-weight: 700;
        color: var(--ink);
        margin-bottom: 8px;
        letter-spacing: 0;
    }

    .login-subtitle {
        color: var(--muted);
        font-size: 0.95rem;
        font-weight: 400;
    }

    .dashboard-header {
        background: var(--panel);
        padding: 20px 40px;
        margin: -70px -70px 30px -70px;
        border-bottom: 1px solid var(--line);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .dashboard-title {
        font-size: 1.8rem;
        font-weight: 700;
        color: var(--ink);
        margin: 0;
    }

    .dashboard-container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 24px;
        background: rgba(255, 255, 255, 0.72);
        border-radius: 8px;
        border: 1px solid rgba(226, 232, 240, 0.9);
        box-shadow: 0 18px 45px rgba(15, 23, 42, 0.07);
        margin-top: 20px;
    }

    .welcome-banner {
        background: linear-gradient(135deg, var(--primary) 0%, #0f766e 100%);
        padding: 30px;
        border-radius: 8px;
        color: white;
        margin-bottom: 30px;
        box-shadow: 0 14px 30px rgba(37, 99, 235, 0.16);
    }

    .welcome-banner h2 {
        margin: 0 0 8px 0;
        font-size: 1.8rem;
        font-weight: 600;
        color: white !important;
        border: none !important;
        padding: 0 !important;
    }

    .welcome-banner p {
        margin: 0;
        opacity: 0.95;
        font-size: 1rem;
    }

    .stat-card {
        background: var(--panel);
        padding: 24px;
        border-radius: 8px;
        color: var(--ink);
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
        transition: all 0.3s ease;
        border: 1px solid var(--line);
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
        margin: 10px 0;
        color: var(--primary);
    }

    .stat-label {
        font-size: 0.85rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
    }

    .section-header {
        font-size: 1.3rem;
        font-weight: 600;
        color: var(--ink);
        margin: 30px 0 20px 0;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--line);
    }

    .stButton > button {
        background: var(--primary);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px 30px;
        font-weight: 600;
        font-size: 1rem;
        transition: all 0.3s ease;
        box-shadow: 0 10px 20px rgba(37, 99, 235, 0.18);
        width: 100%;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        background: var(--primary-dark);
        box-shadow: 0 14px 24px rgba(37, 99, 235, 0.22);
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        background: #eaf2ff;
        padding: 6px;
        border-radius: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background: transparent;
        border-radius: 6px;
        padding: 10px 20px;
        font-weight: 600;
        color: #475569;
        border: none;
    }

    .stTabs [aria-selected="true"] {
        background: white;
        color: var(--primary);
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
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

    .uploadedFile {
        background: var(--soft);
        border: 2px dashed #bfdbfe;
        border-radius: 8px;
        padding: 20px;
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
        margin: 5px;
        font-weight: 600;
        font-size: 0.85rem;
        border: 1px solid #bfdbfe;
    }

    .skill-badge-missing {
        background: #fee2e2;
        color: #991b1b;
        border-color: #fecaca;
    }

    .success-box {
        background: #ecfdf5;
        padding: 16px 20px;
        border-radius: 8px;
        color: #065f46;
        margin: 15px 0;
        font-weight: 500;
        border: 1px solid #a7f3d0;
    }

    .warning-box {
        background: #fffbeb;
        padding: 16px 20px;
        border-radius: 8px;
        color: #92400e;
        margin: 15px 0;
        font-weight: 500;
        border: 1px solid #fde68a;
    }

    .info-box {
        background: #eff6ff;
        padding: 16px 20px;
        border-radius: 8px;
        color: #1e3a8a;
        margin: 15px 0;
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
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
        margin-bottom: 20px;
    }

    .stSelectbox > div > div {
        border-radius: 8px;
        border: 1px solid var(--line);
    }

    .sign-out-btn button {
        background: white !important;
        color: var(--primary) !important;
        border: 1px solid #bfdbfe !important;
        padding: 8px 20px !important;
        font-size: 0.9rem !important;
        box-shadow: none !important;
    }

    .sign-out-btn button:hover {
        background: #eff6ff !important;
        color: var(--primary-dark) !important;
    }

    @media (max-width: 768px) {
        .login-container {
            padding: 28px 22px;
            margin-top: 24px;
        }

        .dashboard-container {
            padding: 12px;
        }

        .welcome-banner {
            padding: 24px;
        }

        .stat-card {
            margin-bottom: 12px;
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
    if 'page' not in st.session_state:
        st.session_state.page = 'auth'
    if 'local_analyses' not in st.session_state:
        st.session_state.local_analyses = load_local_analyses()
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
    """Show modern authentication page"""
    # Center the login card
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div class="login-container">
            <div class="login-header">
                <div class="login-title"> Smart Career</div>
                <div class="login-subtitle">Advanced Resume Analysis & Skill Gap Detection</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        tab1, tab2 = st.tabs(["🔐 Sign In", "📝 Sign Up"])
        
        with tab1:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("signin_form", clear_on_submit=False):
                email = st.text_input("📧 Email Address", placeholder="your.email@example.com", key="signin_email")
                password = st.text_input("🔒 Password", type="password", placeholder="Enter your password", key="signin_password")
                
                st.markdown("<br>", unsafe_allow_html=True)
                submit = st.form_submit_button("Sign In", use_container_width=True)
                
                if submit:
                    if email and password:
                        with st.spinner("Signing in..."):
                            result = st.session_state.auth_service.sign_in(email, password)
                            if result['success']:
                                st.session_state.authenticated = True
                                st.session_state.user = result['user']
                                st.session_state.page = 'dashboard'
                                st.success("✅ " + result['message'])
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ " + result['message'])
                    else:
                        st.warning("⚠️ Please fill in all fields")
        
        with tab2:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.form("signup_form", clear_on_submit=False):
                full_name = st.text_input("👤 Full Name", placeholder="Your Name", key="signup_name")
                email = st.text_input("📧 Email Address", placeholder="your.email@example.com", key="signup_email")
                password = st.text_input("🔒 Password", type="password", placeholder="Choose a strong password", key="signup_password")
                password_confirm = st.text_input("🔒 Confirm Password", type="password", placeholder="Re-enter your password", key="signup_confirm")
                
                st.markdown("<br>", unsafe_allow_html=True)
                submit = st.form_submit_button("Create Account", use_container_width=True)
                
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

def show_dashboard():
    """Show modern dashboard"""
    # Header with sign out
    col1, col2 = st.columns([4, 1])
    with col1:
        user_name = st.session_state.user.email.split('@')[0].title() if st.session_state.user else "User"
        st.markdown(f"""
        <div class="welcome-banner">
            <h2>👋 Welcome back, {user_name}!</h2>
            <p>Track your resume analysis, match scores, and skill development journey</p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="sign-out-btn">', unsafe_allow_html=True)
        if st.button("🚪 Sign Out", use_container_width=True):
            st.session_state.auth_service.sign_out()
            st.session_state.authenticated = False
            st.session_state.user = None
            st.session_state.page = 'auth'
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Statistics Cards
    stats = st.session_state.resume_repo.get_resume_statistics(st.session_state.user.id)
    
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
            <div class="stat-label">🎯 Avg Match</div>
            <div class="stat-number">{stats['average_match_score']}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">💡 Unique Skills</div>
            <div class="stat-number">{stats['unique_skills']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
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
    st.markdown('<div class="section-header">📤 Upload Your Resume</div>', unsafe_allow_html=True)
    st.markdown("**Supports PDF and DOCX files. Scanned documents automatically processed with OCR.**")
    
    uploaded = st.file_uploader(
        "Choose your resume file",
        type=["pdf", "docx"],
        help="Upload your resume for AI-powered analysis"
    )
    
    if uploaded:
        ts = time.strftime("%Y%m%d-%H%M%S")
        safe_name = uploaded.name.replace(" ", "_")
        saved_path = UPLOADS_DIR / f"{ts}__{safe_name}"
        
        with saved_path.open("wb") as f:
            f.write(uploaded.getbuffer())
        
        st.markdown('<div class="success-box">✅ Resume uploaded successfully! Analyzing now...</div>', unsafe_allow_html=True)
        
        with st.spinner("🔍 Analyzing your resume with AI..."):
            progress = st.progress(0)
            for i in range(100):
                time.sleep(0.01)
                progress.progress(i + 1)
            
            roles_map = load_skill_dataset_from_db()
            result = analyze_resume(str(saved_path))
            
            resume_record = st.session_state.resume_repo.save_resume(
                user_id=st.session_state.user.id,
                filename=uploaded.name,
                file_type=uploaded.type.split('/')[-1],
                raw_text="",
                parsed_data=result["parsed"],
                file_size=uploaded.size
            )
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown('<div class="section-header">🧩 Extracted Information</div>', unsafe_allow_html=True)
            
            skills = result["parsed"].get("skills", [])
            edu = result["parsed"].get("education", [])
            exp = result["parsed"].get("experience", [])
            
            st.markdown("**💡 Skills Found:**")
            if skills:
                skills_html = " ".join([f'<span class="skill-badge">{skill.title()}</span>' 
                                       for skill in sorted(skills)[:20]])
                st.markdown(skills_html, unsafe_allow_html=True)
                if len(skills) > 20:
                    st.info(f"+ {len(skills) - 20} more skills")
            else:
                st.markdown('<div class="warning-box">⚠️ No skills detected</div>', unsafe_allow_html=True)
            
            st.markdown("<br>**🎓 Education:**")
            if edu:
                for e in edu[:3]:
                    st.write(f"• {e}")
            else:
                st.write("—")
            
            st.markdown("<br>**💼 Experience:**")
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
                    "resume_id": resume_record["id"] if resume_record else f"local-{ts}",
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
        
        if saved_path.exists():
            saved_path.unlink()

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
    
    for resume in resumes:
        # ✅ Safe filename
        filename = resume.get("filename", "Unknown File")
        
        # ✅ Safe upload date handling
        upload_date = resume.get("upload_date")
        if isinstance(upload_date, str):
            display_date = upload_date[:10]
        elif isinstance(upload_date, datetime):
            display_date = upload_date.strftime("%Y-%m-%d")
        else:
            display_date = "Unknown Date"
        
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
                    use_container_width=True
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
        st.plotly_chart(fig, use_container_width=True)
    
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
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("<br>**🏆 Top Performing Analyses**", unsafe_allow_html=True)
    top_analyses = df.nlargest(5, 'match_score')[['target_role', 'match_score', 'analysis_date']]
    top_analyses['analysis_date'] = top_analyses['analysis_date'].dt.strftime('%Y-%m-%d')
    top_analyses.columns = ['Role', 'Match Score (%)', 'Date']
    st.dataframe(top_analyses, use_container_width=True, hide_index=True)

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
