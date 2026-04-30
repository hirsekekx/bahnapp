"""Streamlit-side Google OAuth (OIDC) login + email allowlist gate.

Uses Streamlit's query params for the auth-code callback. Persists the user in
st.session_state["user"]. Requires the redirect URI configured in the Google
Console to point back at the Streamlit app (e.g. http://host:8501/).
"""
from __future__ import annotations

import secrets
from typing import Optional
from urllib.parse import urlencode

import httpx
import streamlit as st
from authlib.jose import jwt

from bahnapp.config import get_settings

GOOGLE_AUTHZ_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


def _build_authz_url(state: str) -> str:
    s = get_settings()
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHZ_URL}?{urlencode(params)}"


def _exchange_code(code: str) -> dict:
    s = get_settings()
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": s.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def _verify_id_token(id_token: str) -> dict:
    jwks = httpx.get(GOOGLE_JWKS_URL, timeout=10.0).json()
    claims = jwt.decode(id_token, jwks)
    claims.validate()
    return dict(claims)


def _get_query_params() -> dict:
    qp = st.query_params
    return {k: (v if isinstance(v, str) else (v[0] if v else "")) for k, v in qp.items()}


def require_login() -> Optional[dict]:
    """Render login flow. Returns user dict if authorized, else stops the script."""
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        st.warning(
            "Google OAuth ist nicht konfiguriert. Setze GOOGLE_CLIENT_ID/SECRET in der .env. "
            "Dev-Modus: Login wird übersprungen."
        )
        return {"email": "dev@local", "name": "Dev"}

    user = st.session_state.get("user")
    if user:
        return user

    qp = _get_query_params()
    if "code" in qp and "state" in qp:
        expected = st.session_state.get("oauth_state")
        if expected and qp["state"] == expected:
            try:
                tokens = _exchange_code(qp["code"])
                claims = _verify_id_token(tokens["id_token"])
                email = (claims.get("email") or "").lower()
                if email in s.allowed_emails_set:
                    st.session_state["user"] = {
                        "email": email,
                        "name": claims.get("name", ""),
                        "picture": claims.get("picture", ""),
                    }
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(f"Zugriff verweigert für {email}.")
                    st.stop()
            except Exception as exc:
                st.error(f"Login fehlgeschlagen: {exc}")
                st.stop()
        else:
            st.error("OAuth-State stimmt nicht überein. Bitte erneut einloggen.")
            st.stop()

    state = secrets.token_urlsafe(24)
    st.session_state["oauth_state"] = state
    st.title("Bahn-Ausfall-Tracker")
    st.write("Bitte mit Google anmelden.")
    st.link_button("Mit Google anmelden", _build_authz_url(state))
    st.stop()
    return None


def logout_button() -> None:
    if st.sidebar.button("Logout"):
        st.session_state.pop("user", None)
        st.session_state.pop("oauth_state", None)
        st.rerun()
