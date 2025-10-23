"""smart_auth.py – Auth0 PKCE helper (re‑built from the working flow in
fhir_textual.py)

Key design notes
----------------
* **PKCE**: uses `authlib.integrations.requests_client.OAuth2Session` with
  automatic code‑verifier / challenge.
* **One‑shot loop‑back HTTP server** on the *same* port (`8900`) as the working
  demo – grabs the `code` then shuts down.
* **Blocking** `login()` call that returns the *access token*; the instance
  keeps `self.token` and (optionally) `self.patient_ref` if the Auth0 tenant
  includes `user_metadata.patient`.
* No manual Content‑Length headers, no threading complexity – copied straight
  from the demo that “works like a charm”.

Replace the placeholder constants (or rely on environment variables) before
use.
"""

from __future__ import annotations

import base64
import http.server
import json
import logging
import os
import socketserver
import webbrowser
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from authlib.integrations.requests_client import OAuth2Session
#from jose import jwt


logger = logging.getLogger(__name__)
logger.propagate = True
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv()) 

# ---------------------------------------------------------------------------
# Config – mirrors fhir_textual.py (env‑override friendly)
# ---------------------------------------------------------------------------
AUTH_DOMAIN   = os.getenv("AUTH0_DOMAIN",   "dev-1h5yru1mv5rucu2k.us.auth0.com")
CLIENT_ID     = os.getenv("AUTH0_CLIENT_ID", "fIv1uGKhCXanH4iVcTNagE3eFLFIfPDb")
CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET", "58-d_89jb7CYM2kt6gqkvtElzSaRdXUkJFBNG_TjePO2eHoWcbrN9zHAvyP2UHWV")
FHIR_BASE     = os.getenv("FHIR_BASE",     "https://iris.rpaihtnv03ms.sandbox-eng-paas.isccloud.io/csp/healthshare/fhir/fhir/r4a")
REDIRECT_URI  = os.getenv("AUTH0_REDIRECT_URI", "http://127.0.0.1:8900/cb")
SCOPE         = os.getenv("AUTH0_SCOPE", "openid profile user/*.*")
PATIENT_CLAIM = os.getenv("PATIENT_CLAIM_NS", "https://fhir.example.com/claims/patient")

# ---------------------------------------------------------------------------
# One‑shot TCP server (identical to fhir_textual.py)
# ---------------------------------------------------------------------------

class _OneShotTCPServer(socketserver.TCPServer):
    allow_reuse_address = True  # "It's fine, I know this port"

class _CodeHandler(http.server.BaseHTTPRequestHandler):
    """Minimal handler to extract the ?code=… query param."""
    code: str | None = None  # filled by the server instance

    def do_GET(self):  # noqa: N802
        self.send_response(200); self.end_headers()
        self.wfile.write(b"<html><body><h2>You may now close this tab.</h2></body></html>")
        params = parse_qs(urlparse(self.path).query)
        self.server.code = params.get("code", [None])[0]  # type: ignore[attr-defined]

    def log_message(self, *_):  # silence default logging
        return

# ---------------------------------------------------------------------------
# SmartAuth – blocking helper
# ---------------------------------------------------------------------------

class SmartAuth:
    """Re‑usable Auth0 PKCE login helper (blocking)."""

    def __init__(self) -> None:
        self.token: Optional[str] = None           # Bearer token
        self.id_token: Optional[str] = None        # raw ID token (if returned)
        self.patient_ref: Optional[str] = None     # e.g. "Patient/1"
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def login(self) -> str:
        """Launch browser, run PKCE flow, return access token (blocks)."""
        logger.info("Starting SMART on FHIR PKCE flow …")

        oauth = OAuth2Session(
            CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            code_challenge_method="S256",
        )

    

        auth_url = oauth.create_authorization_url(
            f"https://{AUTH_DOMAIN}/authorize",
            audience=FHIR_BASE,
            prompt="consent",
        )[0]
        webbrowser.open(auth_url)
        logger.info("Browser opened → %s", auth_url)

        # --- one‑shot server ---
        parsed = urlparse(REDIRECT_URI)
        host, port = parsed.hostname, parsed.port or 80
        with _OneShotTCPServer((host, port), _CodeHandler) as srv:
            while getattr(srv, "code", None) is None:
                srv.handle_request()
        code: str = srv.code  # type: ignore[attr-defined]
        logger.info("Authorization code received: %s", code)

        # --- token exchange ---
        try:
            token_dict = oauth.fetch_token(
                f"https://{AUTH_DOMAIN}/oauth/token",
                code=code,
                client_secret=CLIENT_SECRET,
                redirect_uri=REDIRECT_URI,

            )
            self.token = token_dict["access_token"]
            self.id_token = token_dict.get("id_token")
            logger.info("Full token response: %s", json.dumps(token_dict, indent=2))
            logger.info("Access token acquired (masked): %s", self._mask(self.token))
        except Exception as e:
            logger.info("Failed to exchange code for token.")
            raise

        # Optional: extract patient‑ref
        #self.patient_ref = self._extract_patient()
        return self.token

    def logout(self) -> None:
        """Clear local token (add revocation call if your IdP supports it)."""
        self.token = None
        self.id_token = None
        self.patient_ref = None
        logger.info("SmartAuth: local token cleared.")
        webbrowser.open(f"https://{AUTH_DOMAIN}/v2/logout?federated&returnTo=http%3A%2F%2Flocalhost%3A8900%2F&client_id={CLIENT_ID }")



    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _extract_patient(self) -> Optional[str]:

        if self.token:
            try:
                claims = jwt.get_unverified_claims(self.token)
                self.patient_ref = claims.get("patient") # store for later
                logger.info("Patient id reference from access token: %s",  self.patient_ref )
                return  self.patient_ref 
            except Exception as exc:  # noqa: BLE001
                logger.info("Access parse failed: %s", exc)
                return None
       
    @staticmethod
    def _mask(tok: str, n: int = 8) -> str:
        return tok[:n] + "…" if tok else "<none>"