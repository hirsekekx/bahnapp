"""Helpers shared between Streamlit pages."""
from __future__ import annotations

import streamlit as st

from bahnapp.auth.google_oidc import logout_button, require_login


def gate() -> dict:
    user = require_login()
    st.sidebar.success(f"Eingeloggt: {user['email']}")
    logout_button()
    return user
