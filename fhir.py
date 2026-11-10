"""Read a patient's chart from a FHIR R4 server.

FHIR stores a chart as separate resources that point to the patient:
Patient (who), Condition (diagnoses), Observation (labs, vitals) and
MedicationRequest (prescriptions) and DocumentReference (clinical notes).
To read a chart we search each resource
type for `patient=<id>`.

Usage: uv run fhir.py pa-01      (prints that patient's chart)
"""

import base64
import os
import sys

import httpx

FHIR_BASE = os.environ.get("FHIR_BASE", "http://localhost:8080/fhir")

client = httpx.Client(
    base_url=FHIR_BASE,
    headers={"Accept": "application/fhir+json"},
    timeout=30,
)


def search(resource_type: str, **params) -> list[dict]:
    """All resources matching a search, following the server's paging links."""
    resources = []
    response = client.get(resource_type, params=params)
    while True:
        response.raise_for_status()
        bundle = response.json()
        resources += [entry["resource"] for entry in bundle.get("entry", [])]
        next_url = next(
            (
                link["url"]
                for link in bundle.get("link", [])
                if link["relation"] == "next"
            ),
            None,
        )
        if next_url is None:
            return resources
        response = client.get(next_url)


def get_patient(patient_id: str) -> dict:
    response = client.get(f"Patient/{patient_id}")
    response.raise_for_status()
    return response.json()


def get_conditions(patient_id: str) -> list[dict]:
    return search("Condition", patient=patient_id)


def get_observations(patient_id: str, loinc_code: str | None = None) -> list[dict]:
    """Newest first. Pass a LOINC code (e.g. "4548-4" for A1C) to get one test."""
    params = {"patient": patient_id, "_sort": "-date"}
    if loinc_code:
        params["code"] = f"http://loinc.org|{loinc_code}"
    return search("Observation", **params)


def get_medication_requests(patient_id: str) -> list[dict]:
    return search("MedicationRequest", patient=patient_id)


def get_notes(patient_id: str) -> list[dict]:
    """Clinical notes, newest first, as {"ref", "date", "text"}."""
    notes = []
    for doc in search("DocumentReference", patient=patient_id, _sort="-date"):
        attachment = doc["content"][0]["attachment"]
        notes.append(
            {
                "ref": f"DocumentReference/{doc['id']}",
                "date": doc["date"][:10],
                "text": base64.b64decode(attachment["data"]).decode(),
            }
        )
    return notes


def coding(concept: dict) -> str:
    """'E11.9 Type 2 diabetes mellitus ...' from a CodeableConcept."""
    c = concept["coding"][0]
    return f"{c['code']} {c.get('display', '')}".strip()


def print_chart(patient_id: str) -> None:
    patient = get_patient(patient_id)
    name = patient["name"][0]
    print(
        f"{patient_id}: {' '.join(name['given'])} {name['family']}, "
        f"{patient['gender']}, born {patient['birthDate']}"
    )

    print("\nConditions:")
    for c in get_conditions(patient_id):
        status = c["clinicalStatus"]["coding"][0]["code"]
        print(f"  {coding(c['code'])}  ({status}, since {c['onsetDateTime']})")

    print("\nObservations (newest first):")
    for o in get_observations(patient_id):
        q = o["valueQuantity"]
        print(
            f"  {o['effectiveDateTime']}  {coding(o['code'])}: {q['value']} {q['unit']}"
        )

    print("\nMedication requests:")
    for m in get_medication_requests(patient_id):
        print(
            f"  {coding(m['medicationCodeableConcept'])}  "
            f"({m['status']}, written {m['authoredOn']})"
        )

    print("\nNotes:")
    for note in get_notes(patient_id):
        print(f"  {note['date']}  {note['ref']}\n    {note['text']}")


if __name__ == "__main__":
    print_chart(sys.argv[1] if len(sys.argv) > 1 else "pa-01")
