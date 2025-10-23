import logging
from typing import List

from textual.app import App, ComposeResult
from textual.widgets import (
    Header,
    Footer,
    Button,
    Static,
    Log,
    DataTable,
)
from textual.containers import Horizontal, Vertical


from smart_auth import SmartAuth
import fhir_client as fhir


SMART_SCOPES = [
    "openid",
    "profile",
    "offline_access",
    "user/*.*",
]

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename="smart_fhir.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="w",  # Overwrite on each run
)
logger = logging.getLogger(__name__)


class SmartFHIRDemo(App):
    """A Textual demo app that shows login state and patient data in a table."""

    CSS_PATH = "app.tcss" # You can add a .css file for nicer layout/styling

    # ------------------------------------------------------------------
    # Compose the UI
    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()

        # Control row: Login + status + other buttons in a single horizontal line
        with Horizontal(id="controls"):
            yield Button("Login", id="login")
            yield Button("Logout", id="logout")
            yield Button("Patients", id="patients")
            yield Static("[yellow]Logged Out[/yellow]", id="status")

        # Patient table + log area stacked vertically
        with Vertical():
            yield DataTable(id="patient_table")
            yield Log(id="log", auto_scroll=True)

        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_mount(self):
        """Initialize widgets after the DOM is ready."""
        table = self.query_one("#patient_table", DataTable)
        table.add_columns("FHIR ID", "Last Name")
        table.cursor_type = "row"  # nicer UX when selecting rows

    # ------------------------------------------------------------------
    # Helper – update login status label
    # ------------------------------------------------------------------
    def _set_status(self, logged_in: bool) -> None:
        status = self.query_one("#status", Static)
        if logged_in:
            status.update("[green]Logged In[/green]")
        else:
            status.update("[yellow]Logged Out[/yellow]")

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------
    def on_button_pressed(self, event):
    
        table: DataTable = self.query_one("#patient_table", DataTable)

        if event.button.id == "login":
            self.auth = SmartAuth()
            try:
                self.auth.login()
                message = "Logged in."
                self._set_status(True)
                logger.info("Logged in.")
            except Exception as exc:
                logger.error(f"Login failed: {exc}")
                self._set_status(False)
            

        elif event.button.id == "logout":
            if hasattr(self, "auth") and self.auth.token:
                self.auth.logout()
                message = "Logged out."
                self._set_status(False)
                logger.info(message)
            else:
                logger.warning("Already logged out.")

        elif event.button.id == "patients":
            if not hasattr(self, "auth") or self.auth.token is None:
                logger.error("Please login first.")
                return

            token = self.auth.token
            try:
                patients = fhir.search_patients("_maxresults=10", token)
            except Exception as exc:
                logger.error("FHIR request failed: %s", exc)
                return

            # Clear prior table data and repopulate
            table.clear()
            for patient in patients:
                last_name: str = (
                    patient.name[0].family if patient.name and patient.name[0].family else "(no family name)"
                )
                table.add_row(patient.id, last_name)
                logger.info("%s – %s", patient.id, last_name)

            logger.info(f"Loaded {len(patients)} patients.")


if __name__ == "__main__":
    SmartFHIRDemo().run()
