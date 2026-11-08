"""Load synthetic test patients into the local FHIR server.

Each patient is one prior authorization case: a doctor has ordered semaglutide
(a GLP-1 medicine) and the chart either does or does not support it. The cases
differ in one thing at a time, so later we can check that the copilot reaches
the expected decision for the expected reason.

All patients are fictional. Dates are relative to today, so "A1C from 2 months
ago" stays 2 months old whenever you run this.

Every resource has a fixed id and is sent with PUT, so running this again
updates the same resources instead of creating duplicates.

Usage: uv run seed.py
"""

from datetime import date, timedelta

from fhir import FHIR_BASE, client

ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
UCUM = "http://unitsofmeasure.org"

T2D = ("E11.9", "Type 2 diabetes mellitus without complications")
OBESITY = ("E66.9", "Obesity, unspecified")
A1C = ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood")
BMI = ("39156-5", "Body mass index (BMI) [Ratio]")
METFORMIN = ("6809", "metformin")
SEMAGLUTIDE = ("1991302", "semaglutide")

# id, name, birth date, gender, (expected decision, why), chart facts.
# Decisions: "meets", "not_met" (a criterion fails), "missing" (documentation
# needed before a decision can be made).
# Facts: ("condition", code, days ago) / ("lab", code, value, unit, days ago)
#        / ("med", code, days ago). The semaglutide order is added to every case.
CASES = [
    (
        "pa-01",
        ("Rivera", "Ana"),
        "1968-04-12",
        "female",
        ("meets", "meets all criteria"),
        [
            ("condition", T2D, 900),
            ("lab", A1C, 8.9, "%", 240),
            ("lab", A1C, 8.4, "%", 60),
            ("med", METFORMIN, 400),
        ],
    ),
    (
        "pa-02",
        ("Okafor", "James"),
        "1975-09-30",
        "male",
        ("not_met", "no metformin trial (step therapy not met)"),
        [
            ("condition", T2D, 200),
            ("lab", A1C, 7.8, "%", 30),
        ],
    ),
    (
        "pa-03",
        ("Chen", "Lily"),
        "1990-01-22",
        "female",
        ("not_met", "no type 2 diabetes diagnosis (weight loss only)"),
        [
            ("condition", OBESITY, 500),
            ("lab", BMI, 33.1, "kg/m2", 20),
            ("lab", A1C, 5.6, "%", 20),
        ],
    ),
    (
        "pa-04",
        ("Novak", "Peter"),
        "1959-07-03",
        "male",
        ("missing", "latest A1C is over a year old (missing documentation)"),
        [
            ("condition", T2D, 1500),
            ("lab", A1C, 8.1, "%", 420),
            ("med", METFORMIN, 1200),
        ],
    ),
]


def iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def concept(system: str, code_display: tuple[str, str]) -> dict:
    code, display = code_display
    return {"coding": [{"system": system, "code": code, "display": display}]}


def build_resources(case) -> list[dict]:
    pid, (family, given), birth_date, gender, _expected, facts = case
    subject = {"reference": f"Patient/{pid}"}
    resources = [
        {
            "resourceType": "Patient",
            "id": pid,
            "name": [{"family": family, "given": [given]}],
            "birthDate": birth_date,
            "gender": gender,
        }
    ]
    for n, fact in enumerate(facts, start=1):
        kind = fact[0]
        if kind == "condition":
            _, code, days_ago = fact
            resources.append(
                {
                    "resourceType": "Condition",
                    "id": f"{pid}-condition-{n}",
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "code": concept(ICD10, code),
                    "subject": subject,
                    "onsetDateTime": iso(days_ago),
                }
            )
        elif kind == "lab":
            _, code, value, unit, days_ago = fact
            resources.append(
                {
                    "resourceType": "Observation",
                    "id": f"{pid}-observation-{n}",
                    "status": "final",
                    "code": concept(LOINC, code),
                    "subject": subject,
                    "effectiveDateTime": iso(days_ago),
                    "valueQuantity": {
                        "value": value,
                        "unit": unit,
                        "system": UCUM,
                        "code": unit,
                    },
                }
            )
        elif kind == "med":
            _, code, days_ago = fact
            resources.append(
                {
                    "resourceType": "MedicationRequest",
                    "id": f"{pid}-medication-{n}",
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": concept(RXNORM, code),
                    "subject": subject,
                    "authoredOn": iso(days_ago),
                }
            )

    # The order waiting for prior authorization: a draft, not yet active.
    resources.append(
        {
            "resourceType": "MedicationRequest",
            "id": f"{pid}-order",
            "status": "draft",
            "intent": "order",
            "medicationCodeableConcept": concept(RXNORM, SEMAGLUTIDE),
            "subject": subject,
            "authoredOn": iso(0),
            "dosageInstruction": [{"text": "0.25 mg subcutaneously once weekly"}],
        }
    )
    return resources


def main() -> None:
    # One transaction: the server applies all entries or none.
    entries = []
    for case in CASES:
        for resource in build_resources(case):
            url = f"{resource['resourceType']}/{resource['id']}"
            entries.append(
                {"resource": resource, "request": {"method": "PUT", "url": url}}
            )
    bundle = {"resourceType": "Bundle", "type": "transaction", "entry": entries}

    response = client.post("", json=bundle)
    response.raise_for_status()
    print(f"Loaded {len(entries)} resources into {FHIR_BASE}")
    for pid, _name, _birth, _gender, (decision, why), _facts in CASES:
        print(f"  {pid}: {decision:8} {why}")


if __name__ == "__main__":
    main()
