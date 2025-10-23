"""
Textual SMART-on-FHIR demo:
  • Press L to log in via browser (PKCE flow)
  • After auth, Patient/2 demographics appear
"""

from __future__ import annotations
import asyncio, json, os, webbrowser, http.server, socketserver
from urllib.parse import urlparse, parse_qs
import requests
from authlib.integrations.requests_client import OAuth2Session
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Header, Footer, Button, Log  
from pathlib import Path
import base64, json
import socketserver
# ⇢ 1. load .env *early*
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv()) 

LOG_FILE = Path("smart_fhir_log.txt")
AUTH_DOMAIN      = os.environ["AUTH0_DOMAIN"]
CLIENT_ID        = os.environ["AUTH0_CLIENT_ID"]
CLIENT_SECRET    = os.environ["AUTH0_CLIENT_SECRET"]
FHIR_BASE        = "https://3.17.248.24/csp/healthshare/fhir/fhir/r4"
#REDIRECT_URI     = "http://127.0.0.1:8765/cb"          # registered in Auth0
REDIRECT_URI     = "http://127.0.0.1:8900/cb"          # registered in Auth0
SCOPE            = "user/*.*"

if not all([AUTH_DOMAIN, CLIENT_ID, CLIENT_SECRET]):
    raise RuntimeError(
        "One or more Auth0 variables are missing. "
        "Check your .env file or export them in the shell."
    )

class OneShotTCPServer(socketserver.TCPServer):
    allow_reuse_address = True          # 👈 tell OS “it’s fine, I know this port”

class CodeHandler(http.server.BaseHTTPRequestHandler):
    """Receive ?code=… from the IdP and stash it on the parent server object."""
    code: str | None = None
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"You may now close this tab.")
        params = parse_qs(urlparse(self.path).query)
        self.server.code = params.get("code", [None])[0]  # type: ignore[attr-defined]

class SmartFHIRApp(App):
    CSS_PATH = "app.tcss"  # use default dark theme

    def compose(self) -> ComposeResult:
        yield Header()
        yield Button(" Log in ", id="login_btn", variant="primary")
        yield Button(" Logout ", id="logout_btn", variant="error") 
        yield Log(id="log", highlight=True, auto_scroll=True)
        yield Footer()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
     if event.button.id == "login_btn":
        await self.smart_login()
     elif event.button.id == "logout_btn":
        await self.smart_logout()

    async def smart_logout(self) -> None:
      """Clear local token and (optionally) log the user out of Auth0."""
      log: Log = self.query_one(Log)

      # 1️⃣ Clear local state so the user can press Log-in again
      self.token = None

      # 2️⃣ Tell the user
      self.dual_log(log, "[yellow]Local token cleared; you are now logged out.[/yellow]")

      # 3️⃣ Optionally call Auth0's global logout endpoint in the browser
      logout_url = (
        f"https://{AUTH_DOMAIN}/v2/logout?"
        f"client_id={CLIENT_ID}"

      )
      webbrowser.open(logout_url)            # comment out if you don't want this
      # self.dual_log(log, f"Opened browser → {logout_url}")

    def on_ready(self) -> None:
        # optional: cap the visual height via CSS once the DOM is ready
        self.query_one("#log").styles.max_height = 25

    def dual_log(self, log_widget: Log, message: str) -> None:
      log_widget.write(message)
      with LOG_FILE.open("a") as f:
        f.write(message + "\n")

    async def smart_login(self):
      log: Log = self.query_one(Log)          # type hint for clarity
      LOG_FILE.write_text("SMART on FHIR run log\n\n") 
      self.dual_log(log, "Starting PKCE flow…")

    # 1️⃣  Build the OAuth session (PKCE, redirect URI, scopes)
      oauth = OAuth2Session(
         CLIENT_ID,
         redirect_uri=REDIRECT_URI,
         scope=SCOPE,                       # e.g. "openid profile user/*.read"
        code_challenge_method="S256",
    )

    # 2️⃣  Create the authorization URL *with audience* ⬅️
      auth_url = oauth.create_authorization_url(
        f"https://{AUTH_DOMAIN}/authorize",
        audience=FHIR_BASE,    # ← MUST match IRIS OAuth client
        prompt="consent",            
    )[0]

      webbrowser.open(auth_url)
      self.dual_log(log, f"Opened browser → {auth_url}")

    # 3️⃣  Temporary loop-back HTTP server to capture ?code=
    # 127.0.0.1   works better than localhost, must also have
    # One shot TCP server listenting on 8900
      with OneShotTCPServer(("127.0.0.1", 8900), CodeHandler) as srv:
        while getattr(srv, "code", None) is None:
            srv.handle_request()
      code: str = srv.code                  # type: ignore[attr-defined]
      self.dual_log(log, f"[green]Received code[/green] {code}")

    # 4️⃣  Exchange code → access token (no code_verifier needed on Authlib ≥1.2)
      token = oauth.fetch_token(
        f"https://{AUTH_DOMAIN}/oauth/token",
        code=code,
        client_secret=CLIENT_SECRET,
    )

      self.token = token["access_token"]
      self.dual_log(log, (f"[green]Access token acquired.[/green]"))
      self.dual_log(log, "[green]Decoded token payload:[/green]")
    
      self.dual_log(log, "[blue]Raw bearer token:[/blue]")
      self.dual_log(log, self.token)

      parts = self.token.split(".")
      if len(parts) == 3:
       try:
         payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
         pretty = json.dumps(payload, indent=2)
         self.dual_log(log, "[green]Decoded token payload:[/green]")
         self.dual_log(log, pretty)
       except Exception as e:
         self.dual_log(log, f"[red]Failed to decode token:[/red] {e}")
      else:
       self.dual_log(log, f"[red]Access token is not a JWT or is malformed.[/red]")

      # 5️⃣  Proceed with normal demo
      await self.fetch_patient()

    async def fetch_patient(self):
        log = self.query_one(Log)
        if not getattr(self, "token", None):
          log.write("[red]You are not logged in.[/red]")
          return
        log.write("Fetching Patient/2 …")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/fhir+json"
        }
        r = requests.get(f"{FHIR_BASE}/Patient/2",
                         headers=headers)
        r.raise_for_status()
        log.write(json.dumps(r.json(), indent=2))

if __name__ == "__main__":
    SmartFHIRApp().run()