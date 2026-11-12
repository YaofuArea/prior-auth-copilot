"""Load synthetic test patients into the local FHIR server.

Each patient is one prior authorization case: a doctor has ordered semaglutide
(a GLP-1 medicine) and the chart either does or does not support it. The cases
differ in one thing at a time, so later we can check that the copilot reaches
the expected decision for the expected reason.

Cases pa-05 to pa-07 can only be decided correctly by reading the clinical
note (a DocumentReference); the structured data alone points the wrong way
(pa-05, pa-06) or contains a misleading keyword (pa-07).

All patients are fictional. Dates are relative to today, so "A1C from 2 months
ago" stays 2 months old whenever you run this.

Every resource has a fixed id and is sent with PUT, so running this again
updates the same resources instead of creating duplicates.

Usage: uv run seed.py
"""

import base64
from datetime import date, timedelta

from fhir import FHIR_BASE, client

ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
UCUM = "http://unitsofmeasure.org"

T2D = ("E11.9", "Type 2 diabetes mellitus without complications")
OBESITY = ("E66.9", "Obesity, unspecified")
T1D = ("E10.9", "Type 1 diabetes mellitus without complications")
THYROID_CANCER = ("C73", "Malignant neoplasm of thyroid gland")
A1C = ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood")
BMI = ("39156-5", "Body mass index (BMI) [Ratio]")
METFORMIN = ("6809", "metformin")
SEMAGLUTIDE = ("1991302", "semaglutide")

# id, name, birth date, gender, (expected decision, why), chart facts.
# Decisions: "meets", "not_met" (a criterion fails), "missing" (documentation
# needed before a decision can be made).
# Facts: ("condition", code, days ago) / ("lab", code, value, unit, days ago)
#        / ("med", code, days ago[, status]) / ("note", text, days ago).
# The semaglutide order is added to every case.
# Development cases: used while building the checkers and clarifying the
# policy, so results on them are optimistic.
DEV_CASES = [
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
    (
        "pa-05",
        ("Haddad", "Omar"),
        "1971-11-18",
        "male",
        ("meets", "metformin stopped for intolerance, documented only in a note"),
        [
            ("condition", T2D, 700),
            ("lab", A1C, 8.6, "%", 45),
            ("med", METFORMIN, 300, "stopped"),
            (
                "note",
                (
                    "Follow-up for type 2 diabetes. Metformin 500 mg twice daily was "
                    "started 10 months ago and stopped after 3 weeks because of severe "
                    "diarrhea and abdominal cramping. A trial of extended-release "
                    "metformin 500 mg daily caused the same symptoms and was also "
                    "stopped. Considered intolerant to metformin. A1C remains above "
                    "goal; plan to start a GLP-1 receptor agonist."
                ),
                45,
            ),
        ],
    ),
    (
        "pa-06",
        ("Brennan", "Claire"),
        "1966-02-09",
        "female",
        ("not_met", "family history of medullary thyroid carcinoma, only in a note"),
        [
            ("condition", T2D, 1100),
            ("lab", A1C, 8.0, "%", 50),
            ("med", METFORMIN, 900),
            (
                "note",
                (
                    "Diabetes visit. On metformin 1000 mg twice daily for over 2 years "
                    "with good adherence; A1C still 8.0%. Discussed adding a GLP-1 "
                    "receptor agonist. Family history: mother was diagnosed with "
                    "medullary thyroid carcinoma at age 52. Sister has hypertension."
                ),
                50,
            ),
        ],
    ),
    (
        "pa-07",
        ("Santos", "Maria"),
        "1980-06-25",
        "female",
        ("meets", "note mentions thyroid carcinoma only to rule it out"),
        [
            ("condition", T2D, 600),
            ("lab", A1C, 7.6, "%", 20),
            ("med", METFORMIN, 500),
            (
                "note",
                (
                    "Patient asked about the thyroid cancer warning on the GLP-1 "
                    "medication guide. Reviewed history: no personal or family history "
                    "of medullary thyroid carcinoma or MEN 2. Continue metformin; add "
                    "semaglutide if approved."
                ),
                20,
            ),
        ],
    ),
]

# Test cases: written, with their expected decisions, after policy v1.1 and
# before the agent was run on them.
TEST_CASES = [
    (
        "pa-08",
        ("Kim", "Daniel"),
        "1977-03-14",
        "male",
        ("not_met", "metformin for only 60 days"),
        [
            ("condition", T2D, 400),
            ("lab", A1C, 9.2, "%", 100),
            ("med", METFORMIN, 60),
        ],
    ),
    (
        "pa-09",
        ("Walker", "Grace"),
        "1962-12-01",
        "female",
        ("meets", "A1C exactly 7.0%, 170 days old (both at the boundary)"),
        [
            ("condition", T2D, 1300),
            ("lab", A1C, 7.0, "%", 170),
            ("med", METFORMIN, 800),
        ],
    ),
    (
        "pa-10",
        ("Ibrahim", "Yusuf"),
        "1955-08-19",
        "male",
        ("meets", "metformin contraindicated by kidney function, only in a note"),
        [
            ("condition", T2D, 2000),
            ("lab", A1C, 8.3, "%", 35),
            (
                "note",
                (
                    "Nephrology follow-up. Chronic kidney disease stage 4, latest "
                    "eGFR 24 mL/min/1.73 m2. Metformin is contraindicated at this "
                    "level of kidney function and has never been prescribed. "
                    "Diabetes remains above goal on current therapy."
                ),
                35,
            ),
        ],
    ),
    (
        "pa-11",
        ("Lopez", "Sofia"),
        "1984-05-07",
        "female",
        ("not_met", "latest A1C 6.6%; the higher value in the note is a year old"),
        [
            ("condition", T2D, 900),
            ("lab", A1C, 6.6, "%", 25),
            ("med", METFORMIN, 700),
            (
                "note",
                (
                    "A1C was 8.5% at this time last year and has improved to 6.6% "
                    "on metformin with diet changes. Patient asks about semaglutide "
                    "after hearing about it from a friend."
                ),
                25,
            ),
        ],
    ),
    (
        "pa-12",
        ("Murphy", "Ethan"),
        "1995-10-30",
        "male",
        ("not_met", "type 1 diabetes, not type 2"),
        [
            ("condition", T1D, 4000),
            ("lab", A1C, 8.8, "%", 40),
        ],
    ),
    (
        "pa-13",
        ("Patel", "Asha"),
        "1970-04-02",
        "female",
        ("meets", "thyroid cancer code, but papillary, not medullary"),
        [
            ("condition", T2D, 1000),
            ("condition", THYROID_CANCER, 4000),
            ("lab", A1C, 8.0, "%", 30),
            ("med", METFORMIN, 600),
            (
                "note",
                (
                    "History of papillary thyroid cancer treated with total "
                    "thyroidectomy in 2015, no recurrence. No family history of "
                    "medullary thyroid carcinoma or MEN 2. Diabetes not at goal "
                    "on metformin."
                ),
                30,
            ),
        ],
    ),
    (
        "pa-14",
        ("Nguyen", "Linh"),
        "1973-01-16",
        "female",
        ("not_met", "stopped metformin by choice, not for intolerance"),
        [
            ("condition", T2D, 500),
            ("lab", A1C, 8.4, "%", 15),
            ("med", METFORMIN, 200, "stopped"),
            (
                "note",
                (
                    "Patient stopped metformin about a month after starting it "
                    "because she does not like taking pills every day. She reported "
                    "no side effects. Prefers a once-weekly injection."
                ),
                15,
            ),
        ],
    ),
    (
        "pa-15",
        ("Foster", "Robert"),
        "1961-09-09",
        "male",
        ("missing", "no A1C result on file at all"),
        [
            ("condition", T2D, 300),
            ("med", METFORMIN, 250),
        ],
    ),
]

CASES = DEV_CASES + TEST_CASES


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
            _, code, days_ago, *rest = fact
            resources.append(
                {
                    "resourceType": "MedicationRequest",
                    "id": f"{pid}-medication-{n}",
                    "status": rest[0] if rest else "active",
                    "intent": "order",
                    "medicationCodeableConcept": concept(RXNORM, code),
                    "subject": subject,
                    "authoredOn": iso(days_ago),
                }
            )
        elif kind == "note":
            _, text, days_ago = fact
            # A free-text note is stored as a DocumentReference with the text
            # base64-encoded in an attachment.
            resources.append(
                {
                    "resourceType": "DocumentReference",
                    "id": f"{pid}-note-{n}",
                    "status": "current",
                    "type": concept(LOINC, ("11506-3", "Progress note")),
                    "subject": subject,
                    "date": f"{iso(days_ago)}T09:00:00Z",
                    "content": [
                        {
                            "attachment": {
                                "contentType": "text/plain",
                                "data": base64.b64encode(text.encode()).decode(),
                            }
                        }
                    ],
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
