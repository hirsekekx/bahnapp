"""Streamlit entrypoint. Pages live in `pages/`."""
from __future__ import annotations

import streamlit as st

from bahnapp.auth.google_oidc import logout_button, require_login

st.set_page_config(page_title="Bahn-Ausfall-Tracker", page_icon=None, layout="wide")

user = require_login()

st.sidebar.success(f"Eingeloggt: {user['email']}")
logout_button()

st.title("Bahn-Ausfall-Tracker")
st.write(
    "Beobachtet ICE/IC-Verbindungen über mehrere Tage und berechnet die "
    "Wahrscheinlichkeit eines Ausfalls oder verpassten Anschlusses."
)
st.markdown(
    "Navigation in der Sidebar:\n\n"
    "- **Neuer Job**: Verbindung + Zeitraum auswählen.\n"
    "- **Aktive Jobs**: laufende Beobachtungen verwalten.\n"
    "- **Statistik**: Auswertung pro Job."
)
