import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from supabase import create_client, Client
from dotenv import load_dotenv
import streamlit as st

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH)

_supabase_client: Optional[Client] = None

def init_supabase() -> Client:
    """
    Initialize Supabase client with environment variables.
    This should be called once at application startup.
    """
    global _supabase_client

    try:
        # Use Streamlit secrets (works both locally and in production)
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_KEY"]
    except KeyError:
        # Fallback to environment variables for backward compatibility

        supabase_url = os.getenv("VITE_SUPABASE_URL")
        supabase_key = os.getenv("VITE_SUPABASE_ANON_KEY")

        if not supabase_url or not supabase_key:
            raise ValueError(
                "1. For Streamlit: Add SUPABASE_URL and SUPABASE_KEY to .streamlit/secrets.toml\n"
                "2. For local development: Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in .env file"
                "Missing Supabase credentials. Please ensure VITE_SUPABASE_URL and "
                "VITE_SUPABASE_ANON_KEY are set in your .env file."
            )

    supabase_url = (supabase_url or "").strip()
    supabase_key = (supabase_key or "").strip()

    parsed_url = urlparse(supabase_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError(
            "Invalid Supabase URL. Check SUPABASE_URL or VITE_SUPABASE_URL in your configuration."
        )

    _supabase_client = create_client(supabase_url, supabase_key)
    return _supabase_client

def get_supabase_client() -> Client:
    """
    Get the initialized Supabase client.
    Creates a new client if one doesn't exist.
    """
    global _supabase_client

    if _supabase_client is None:
        _supabase_client = init_supabase()

    return _supabase_client
