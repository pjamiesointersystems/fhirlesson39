"""textual2_app.py – Stand‑alone Textual demo that logs in to a FHIR server,
lists patients, and (via a new Observations button) shows all observations
for the currently highlighted patient.

This version derives directly from `textual.app.App` and now uses **only**
`TabbedContent` to manage the two tabs. The extra `Tabs(...)` widget that
previously duplicated the auto‑generated tabs (and triggered ID mismatches)
has been removed.
"""

from __future__ import annotations

import logging
from typing import Optional

from textual.app import App, ComposeResult
from textual.widgets import (
    Header,
    Footer,
    Button,
    Static,
    Log,
    DataTable,
    TabPane,
    TabbedContent,
)
from textual.containers import Horizontal

import fhir_client as fhir  # your existing helper module
from smart_auth import SmartAuth  # thin SMART‑on‑FHIR OAuth helper

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

# ---------------------------------------------------------------------------
# Helpers – tiny DTOs for what we need from the FHIR resources
# ---------------------------------------------------------------------------

def _patient_display_name(patient) -> str:  # type: ignore[annotation-unchecked]
    """Return a human‑readable display name for a Patient resource."""
    name = getattr(patient, "name", [])
    if name:
        parts: list[str] = []
        if name[0].given:
            parts.extend(name[0].given)
        if name[0].family:
            parts.append(name[0].family)
        return " ".join(parts)
    return "(no name)"


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------
class SmartFHIRDemoV2(App):
    """Minimal stand‑alone Textual demo with Patients + Observations tabs."""

    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    # Will hold the auth helper after login
    auth: Optional[SmartAuth] = None

    # ------------------------------------------------------------------
    # Compose UI
    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:  # type: ignore[override]
        """Build the static widget tree."""
        yield Header()

        # Control row
        with Horizontal(id="controls"):
            yield Button("Login", id="login")
            yield Button("Logout", id="logout")
            yield Button("Patients", id="patients_btn")
            yield Button("Observations", id="observations_btn")
            yield Static("[yellow]Logged Out[/yellow]", id="status")

        # TabbedContent automatically supplies the tab bar
        with TabbedContent(id="main_tabs", initial="patients"):
            with TabPane("Patients", id="patients"):
                yield DataTable(id="patient_table")
            with TabPane("Observations", id="observations"):
                yield DataTable(id="observation_table")

        yield Log(id="log", auto_scroll=True)
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle – post‑mount table setup
    # ------------------------------------------------------------------
        # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_ready(self) -> None:  # type: ignore[override]
        """Configure the two tables once **all** widgets are mounted.

        `on_mount()` fires before TabbedContent finishes mounting the
        content panes, so a `query_one("#patient_table")` can raise the
        *NoMatches* error you saw.  `on_ready()` is invoked after the
        first screen refresh when the full DOM is available, making it a
        safe place to touch widgets created inside `TabPane`s.
        """
        patient_table: DataTable = self.query_one("#patient_table", DataTable)
        patient_table.add_columns("Id", "Name", "Gender", "Birth Date")
        patient_table.cursor_type = "row"

        obs_table: DataTable = self.query_one("#observation_table", DataTable)
        obs_table.add_columns("Code", "Value", "Unit", "When")
        obs_table.cursor_type = "row"

    # ------------------------------------------------------------------
    # Helper – populate patients and observations
    # ------------------------------------------------------------------
    def _load_patients(self) -> None:
        """Fetch and display patients from the FHIR server."""
        if not self._require_auth():
            return

        patient_table: DataTable = self.query_one("#patient_table", DataTable)
        patient_table.clear()

        try:
            patients = fhir.search_patients("_maxresults=10", self.auth.token)
        except Exception as exc:
            logger.error("Failed to fetch patients: %s", exc)
            return

        for patient in patients:
            last_name: str = (
             patient.name[0].family if patient.name and patient.name[0].family else "(no family name)"
            )
            gender = patient.gender
            birthdate = patient.birthDate
            patient_table.add_row(patient.id, last_name, gender, birthdate)
            logger.info("%s – %s", patient.id, last_name, gender, birthdate)
            logger.info(f"Loaded {len(patients)} patients.")

    def _load_observations_for_patient(self, patient_id, token):
     if not self._require_auth():
        return

     obs_table = self.query_one("#observation_table", DataTable)
     obs_table.clear()

     try:
        observations = fhir.observations_for_patient(patient_id, self.auth.token)
     except Exception as exc:
        logger.error("Failed to fetch observations: %s", exc)
        return

     for obs in observations:
        code_display = None
        if getattr(obs, "code", None) and getattr(obs.code, "coding", None):
            code_display = obs.code.coding[0].display or obs.code.coding[0].code
        if not code_display:
            code_display = getattr(obs.code, "text", "(no code)")

        value = "-"
        unit = ""
        if hasattr(obs, "valueQuantity") and obs.valueQuantity:
            value = str(obs.valueQuantity.value)
            unit = obs.valueQuantity.unit or ""

        when = getattr(obs, "effectiveDateTime", "") or getattr(
            getattr(obs, "effectivePeriod", None), "start", ""
        )

        obs_table.add_row(code_display, value, unit, when)

     logger.info("Loaded %d observations for patient %s", len(observations), patient_id)


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _require_auth(self) -> bool:
        if self.auth is None or self.auth.token is None:
            logger.error("Please login first.")
            return False
        return True

    def _update_status(self, text: str, colour: str = "green") -> None:
        status = self.query_one("#status", Static)
        status.update(f"[{colour}]{text}[/{colour}]")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def on_button_pressed(self, event):  # type: ignore[override]
        bid = event.button.id
        tabs = self.query_one("#main_tabs", TabbedContent)

        if bid == "login":
            try:
                self.auth = SmartAuth()
                self.auth.login()  # type: ignore[attr-defined]
                self._update_status("Logged In", "green")
                logger.info("Login successful")
            except Exception as exc:
                self._update_status("Login Failed", "red")
                logger.error("Login failed: %s", exc)

        elif bid == "logout":
            if self.auth:
                try:
                    self.auth.logout()  # type: ignore[attr-defined]
                except Exception:
                    pass
                self.auth = None
            self._update_status("Logged Out", "yellow")
            logger.info("Logged out")

        elif bid == "patients_btn":
            self._load_patients()
            tabs.active = "patients"

        elif bid == "observations_btn":
            patient_table: DataTable = self.query_one("#patient_table", DataTable)
            if patient_table.cursor_row is None:
                logger.error("Please select a patient first.")
                return
            patient_id = patient_table.get_row_at(patient_table.cursor_row)[0]
            self._load_observations_for_patient(patient_id, self.auth.token)
            tabs.active = "observations"

    # ------------------------------------------------------------------
    # Action bindings
    # ------------------------------------------------------------------
    def action_quit(self) -> None:  # noqa: D401
        """Quit the application (bound to q)."""
        self.exit()


if __name__ == "__main__":
    SmartFHIRDemoV2().run()
