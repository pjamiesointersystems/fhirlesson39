# textual3_app.py  – Patient-portal demo (SMART on FHIR, Textual)
# --------------------------------------------------------------
from __future__ import annotations

import logging
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Static, Tab
from textual.widgets import Footer, Label, Markdown, TabbedContent, TabPane
import webbrowser, os


import fhir_client as fhir                # your existing helper
from smart_auth import SmartAuth          # new PKCE helper

AUTH_DOMAIN   = os.getenv("AUTH0_DOMAIN",   "dev-1h5yru1mv5rucu2k.us.auth0.com")
CLIENT_ID     = os.getenv("AUTH0_CLIENT_ID", "7i8fQ6U4ATZl53w4lESWLapJBHkZ8d2p")

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename="smart_fhir.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="w",  # overwrite on each run
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SMART_SCOPES = [
    "openid",
    "offline_access",
    "patient/Patient.r",
    "patient/Observation.r",
]

# ---------------------------------------------------------------------------
# Main Textual app
# ---------------------------------------------------------------------------


class PatientPortal(App):
    CSS_PATH = "app.tcss"              # customise if you have a CSS file
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.auth: SmartAuth | None = None
        self.patient_id: str | None = None

    # --------------------------  UI compose  -------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="controls"):
            yield Button("Login", id="login")
            yield Button("Logout", id="logout", disabled=True)
            yield Static("[yellow]Logged out[/yellow]", id="status")

        with TabbedContent(id="main_tabs"):
            with TabPane("Demographics", id="tab_demo"):
                yield DataTable(id="demo_table")
            with TabPane("Observations", id="tab_obs"):
                yield DataTable(id="obs_table")

    # --------------------------  Event handlers  ---------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "login":
            await self._handle_login()
        elif event.button.id == "logout":
            self._handle_logout()

    # --------------------------  Login / Logout  ---------------------------

    async def _handle_login(self) -> None:
        if self.auth and self.auth.token:
            logger.info("Already logged in.")
            return

       
        try:
            self.auth = SmartAuth()
            self.auth.login()               # blocking, opens browser
        except Exception as exc:
            logger.error("Login failed: %s", exc)
            return

        self.auth.patient_ref = self.auth._extract_patient()
        # Extract patient context
        if not self.auth.patient_ref:
            logger.info("No patient context in token/userinfo.")
            return
        #self.patient_id = self.auth.patient_ref.split("/")[-1]
        self.patient_id = self.auth.patient_ref

        # Update UI
        self.query_one("#logout", Button).disabled = False
        self.query_one("#status", Static).update(
            f"[green]Logged in – Patient {self.patient_id}[/green]"
        )

        # Fetch & show data
        patient = fhir.get_patient(self.patient_id, self.auth.token)
        self._show_demographics(patient)
        self._load_observations()
        # switch to Observations tab
        tabs: TabbedContent = self.query_one("#main_tabs", TabbedContent)
        tabs.active = "tab_obs"

      

   
    

    def _handle_logout(self) -> None:
        if self.auth:
            self.auth.logout()
        self.patient_id = None
        self.query_one("#logout", Button).disabled = True
        self.query_one("#status", Static).update("[yellow]Logged out[/yellow]")
        self.query_one("#demo_table", DataTable).clear()
        self.query_one("#obs_table", DataTable).clear()
        webbrowser.open(f"https://{AUTH_DOMAIN}/v2/logout?federated&returnTo=http%3A%2F%2Flocalhost%3A8900%2F&client_id={CLIENT_ID }")


    # --------------------------  Data helpers  -----------------------------

    def _show_demographics(self, patient) -> None:
        table: DataTable = self.query_one("#demo_table", DataTable)
        table.clear()
        table.add_columns("Field", "Value")

        name = (
            f"{patient.name[0].given[0]} {patient.name[0].family}"
            if patient.name else "—"
        )
        table.add_row("Name", name)
        table.add_row("Gender", patient.gender.capitalize() or "—")
        table.add_row("Birth Date", patient.birthDate or "—")
        table.add_row("Patient ID", patient.id)

    def _load_observations(self) -> None:
        obs_table: DataTable = self.query_one("#obs_table", DataTable)
        obs_table.clear()
        obs_table.add_columns("Code", "Value", "Unit", "When")

        try:
            observations = fhir.observations_for_patient(
                self.patient_id, self.auth.token
            )
        except Exception as exc:
            logger.info("Failed to fetch observations: %s", exc)
            return

        for obs in observations:
            if getattr(obs, "code", None) and obs.code.coding:
                code_display = obs.code.coding[0].display or obs.code.coding[0].code
            else:
                code_display = getattr(obs, "code", {}).get("text", "(no code)")

            value, unit = "-", ""
            if hasattr(obs, "valueQuantity") and obs.valueQuantity:
                value = str(obs.valueQuantity.value)
                unit = obs.valueQuantity.unit or ""

            when = (
                getattr(obs, "effectiveDateTime", "")
                or getattr(getattr(obs, "effectivePeriod", None), "start", "")
            )
            obs_table.add_row(code_display, value, unit, when)

        logger.info("Loaded %d observations", len(observations))

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    PatientPortal().run()