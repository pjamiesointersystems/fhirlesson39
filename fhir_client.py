# fhir_client.py
import logging
from typing import List
import requests
from fhir.resources.patient import Patient
from fhir.resources.observation import Observation
from fhirpathpy import evaluate as fhirpath

FHIR_BASE = "https://iris.rpaihtnv03ms.sandbox-eng-paas.isccloud.io/csp/healthshare/fhir/fhir/r4a"
#FHIR_BASE="https://3.17.248.24/csp/healthshare/fhir/fhir/r4"
logger = logging.getLogger(__name__)  # Inherits handlers configured by the app


def _headers(bearer: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/fhir+json",
        "Content-Type": "application/fhir+json",
        "Prefer": "return=representation",
    }

def get_patient(patient_id: str, token: str) -> Patient:
    url = f"{FHIR_BASE}/Patient/{patient_id}"
    r = requests.get(url, headers=_headers(token))
    r.raise_for_status()
    return Patient.parse_obj(r.json())

def search_patients(params: str, token: str) -> List[Patient]:
    """Search the Patient endpoint and parse the _Bundle_ into `Patient` objects.

    All network activity and key state (URL, status‑code, patient‑count, etc.)
    is logged at INFO level; the OAuth token is logged (masked) at the **same
    level**, so it shows up even when your root logger is set to INFO.
    """
    url = f"{FHIR_BASE}/Patient?{params}"

    # ---- Log request context ------------------------------------------------
    logger.info("FHIR GET %s", url)
    logger.info("OAuth token (masked): %s", token)

    try:
        response = requests.get(
            url,
            headers=_headers(token)
        )
        logger.info("FHIR response status: %s", response.status_code)
        response.raise_for_status()
    except requests.HTTPError as exc:
        logger.error(
            "FHIR request failed (%s): %s", response.status_code, response.text[:300]
        )
        raise  # Let caller decide what to do with the error.

    bundle = response.json()
    raw = fhirpath(bundle, "Bundle.entry.resource")
    patients = [Patient.parse_obj(p) for p in raw if p.get("resourceType") == "Patient"]

    logger.info("Found %d Patient resources", len(patients))
    return patients

 
def observations_for_patient(patient_id: str, token: str) -> list[Observation]:
    url = f"{FHIR_BASE}/Observation?subject=Patient/{patient_id}"
    try:
        logger.info("FHIR GET %s", url)
        logger.info("OAuth token (masked): %s", token)
        r = requests.get(url, headers=_headers(token))
        bundle = r.json()
        raw = fhirpath(bundle, "Bundle.entry.resource")
        return [Observation.parse_obj(o) for o in raw if o.get("resourceType") == "Observation"]

    except Exception as e:
        logger.info(
            "FHIR request failed (%s): %s", r.status_code, r.text[:300]
        )
        raise  # Let caller decide what to do with the error.
   
    