from __future__ import annotations

import os

import streamlit as st

from app.ui_backend.user_keys import USER_API_KEYS, get_saved_keys, load_user_keys_into_environ, save_user_key


BRAND_CSS = """
<style>
    :root {
        --mass-bg: #101218;
        --mass-surface: #171b24;
        --mass-surface-2: #1d2230;
        --mass-border: #2d3550;
        --mass-text: #f4f7fb;
        --mass-muted: #abb4c8;
        --mass-purple: #7a5cff;
        --mass-blue: #5c8cff;
        --mass-yellow: #f0c75e;
    }

    .stApp {
        background: var(--mass-bg);
        color: var(--mass-text);
    }

    [data-testid="stAppViewContainer"] {
        background: var(--mass-bg);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1d28 0%, #151821 100%);
        border-right: 1px solid rgba(122, 92, 255, 0.18);
    }

    [data-testid="stSidebarHeader"] {
        padding-top: 4.4rem !important;
        padding-bottom: 4.6rem !important;
    }

    [data-testid="stLogo"], [data-testid="stSidebarHeader"] img {
        height: 10.1rem !important;
        width: auto !important;
        max-height: 10.1rem !important;
    }

    h1, h2, h3 {
        color: var(--mass-text);
        letter-spacing: 0;
    }

    h1 {
        text-shadow: 0 0 18px rgba(92, 140, 255, 0.10);
    }

    p, label, .stCaption, .stMarkdown, .stText, .stMetricLabel {
        color: var(--mass-text);
    }

    [data-testid="stMetricValue"] {
        color: #ffffff;
    }

    [data-testid="stExpander"] {
        border: 1px solid rgba(122, 92, 255, 0.20);
        border-radius: 8px;
        background: rgba(29, 34, 48, 0.45);
    }

    [data-baseweb="select"] > div,
    .stTextInput input,
    .stNumberInput input,
    .stTextArea textarea {
        background: var(--mass-surface) !important;
        color: var(--mass-text) !important;
        border: 1px solid var(--mass-border) !important;
    }

    .stMultiSelect [data-baseweb="tag"] {
        background: rgba(122, 92, 255, 0.16) !important;
        border: 1px solid rgba(122, 92, 255, 0.35) !important;
    }

    .stButton > button,
    .stDownloadButton > button {
        background: linear-gradient(90deg, rgba(122, 92, 255, 0.95), rgba(92, 140, 255, 0.92));
        color: #ffffff;
        border: 1px solid rgba(240, 199, 94, 0.22);
        border-radius: 8px;
    }

    .stButton > button:hover,
    .stDownloadButton > button:hover {
        border-color: rgba(240, 199, 94, 0.55);
        box-shadow: 0 0 0 1px rgba(240, 199, 94, 0.16), 0 6px 24px rgba(92, 140, 255, 0.18);
    }

    .stButton > button[kind="secondary"] {
        background: var(--mass-surface);
        border: 1px solid rgba(92, 140, 255, 0.28);
    }

    [data-testid="stDataFrame"] {
        border: 1px solid rgba(92, 140, 255, 0.14);
        border-radius: 8px;
        overflow: hidden;
    }

    [data-testid="stDataFrame"] thead tr th {
        background: #1b2030 !important;
        color: #d9def0 !important;
    }

    [data-testid="stCodeBlock"] pre,
    .stJson {
        background: #121722 !important;
        border: 1px solid rgba(122, 92, 255, 0.16);
    }

    a {
        color: #8eafff !important;
    }

    hr {
        border-color: rgba(240, 199, 94, 0.10);
    }
</style>
"""


def init_page(*, page_title: str, page_icon: str) -> None:
    st.set_page_config(page_title=page_title, page_icon=page_icon, layout="wide")
    st.logo("MASS_logo.png")
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
    load_user_keys_into_environ()
    render_api_keys_sidebar()


def render_api_keys_sidebar() -> None:
    """Sezione sidebar per impostare le proprie chiavi OpenRouter / Hugging Face.

    Le chiavi vengono salvate in locale nel file .env (mai versionato su git),
    così chi clona la repo su un'altra macchina può usare i modelli via
    OpenRouter o Hugging Face con il proprio account senza modificare i file
    di configurazione.
    """
    with st.sidebar.expander("🔑 Le tue chiavi API", expanded=False):
        st.caption("Salvate solo in locale in `.env`, mai committate su git.")
        saved = get_saved_keys()
        with st.form("user_api_keys_form", border=False):
            inputs = {
                key: st.text_input(label, value=saved.get(key, ""), type="password", key=f"user_api_key_input_{key}")
                for key, label in USER_API_KEYS.items()
            }
            submitted = st.form_submit_button("Salva chiavi")
        if submitted:
            for key, value in inputs.items():
                save_user_key(key, value)
            st.success("Chiavi salvate.")
            st.rerun()
        for key, label in USER_API_KEYS.items():
            status = "✅ impostata" if os.getenv(key) else "⚠️ non impostata"
            st.caption(f"{label}: {status}")