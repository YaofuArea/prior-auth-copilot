"""Turn the per-criterion findings into what the clinic acts on.

- meets:    a prior authorization request (a FHIR Claim with
            use = "preauthorization") plus a letter of medical necessity.
- missing:  a to-do list of what to add to the chart before submitting.
- not_met:  the reasons the request would not be approved.

The letter is assembled from the findings (the reasons and cited resources
that evaluate.py already checks), not written by another LLM call, so it
cannot add claims that were never checked.
"""

import base64
from datetime import date

from criteria import Finding
from seed import PAYER_ID, PRESCRIBER_ID

POLICY_ID = "EHP-RX-0421"
CRITERION_NAMES = {
    "C1": "Age",
    "C2": "Diagnosis",
    "C3": "Glycemic control",
    "C4": "Step therapy",
    "C5": "No exclusions",
}
ATTESTATION = (
    "I attest that this patient has no personal or family history of medullary "
    "thyroid carcinoma and does not have multiple endocrine neoplasia type 2."
)


def claim_id(patient_id: str) -> str:
    return f"{patient_id}-pa-request"


def letter_id(patient_id: str) -> str:
    return f"{patient_id}-pa-letter"


def build_letter(patient: dict, findings: list[Finding]) -> str:
    name = patient["name"][0]
    full_name = f"{' '.join(name['given'])} {name['family']}"
    lines = [
        (
            f"Re: Prior authorization for semaglutide (Ozempic) 0.25 mg weekly — "
            f"{full_name}, born {patient['birthDate']}"
        ),
        "",
        "To Example Health Plan pharmacy review:",
        "",
        (
            f"I am requesting coverage of semaglutide under policy {POLICY_ID}. "
            "The patient meets each criterion, as documented below:"
        ),
        "",
    ]
    for f in findings:
        if f.criterion == "C5":
            continue  # covered by the prescriber's attestation at the end
        lines.append(f"{f.criterion}. {CRITERION_NAMES[f.criterion]}: {f.reason}")
        if f.evidence:
            lines.append(f"    Supporting records: {', '.join(f.evidence)}")
    lines += ["", ATTESTATION, "", "Dr. Sam Taylor"]
    return "\n".join(lines)


def build_request(patient_id: str, findings: list[Finding], letter: str) -> list[dict]:
    """The Claim and the letter (a DocumentReference), ready to write to FHIR."""
    letter_doc = {
        "resourceType": "DocumentReference",
        "id": letter_id(patient_id),
        "status": "current",
        "description": "Letter of medical necessity",
        "subject": {"reference": f"Patient/{patient_id}"},
        "author": [{"reference": f"Practitioner/{PRESCRIBER_ID}"}],
        "date": f"{date.today().isoformat()}T12:00:00Z",
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "data": base64.b64encode(letter.encode()).decode(),
                }
            }
        ],
    }

    # Every resource the agent cited becomes supporting information, labeled
    # with the criterion it supports, so the payer can open the evidence.
    supporting = []
    for f in findings:
        for ref in f.evidence:
            supporting.append(
                {
                    "sequence": len(supporting) + 1,
                    "category": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/claiminformationcategory",
                                "code": "info",
                            }
                        ],
                        "text": f"{f.criterion} {CRITERION_NAMES[f.criterion]}",
                    },
                    "valueReference": {"reference": ref},
                }
            )
    supporting.append(
        {
            "sequence": len(supporting) + 1,
            "category": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/claiminformationcategory",
                        "code": "attachment",
                    }
                ],
                "text": "Letter of medical necessity",
            },
            "valueReference": {
                "reference": f"DocumentReference/{letter_id(patient_id)}"
            },
        }
    )

    c2 = next(f for f in findings if f.criterion == "C2")
    diagnoses = [ref for ref in c2.evidence if ref.startswith("Condition/")]

    claim = {
        "resourceType": "Claim",
        "id": claim_id(patient_id),
        "status": "active",
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                    "code": "pharmacy",
                }
            ]
        },
        "use": "preauthorization",
        "patient": {"reference": f"Patient/{patient_id}"},
        "created": date.today().isoformat(),
        "provider": {"reference": f"Practitioner/{PRESCRIBER_ID}"},
        "insurer": {"reference": f"Organization/{PAYER_ID}"},
        "priority": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/processpriority",
                    "code": "normal",
                }
            ]
        },
        "prescription": {"reference": f"MedicationRequest/{patient_id}-order"},
        "diagnosis": [
            {"sequence": n, "diagnosisReference": {"reference": ref}}
            for n, ref in enumerate(diagnoses, start=1)
        ],
        "supportingInfo": supporting,
        "insurance": [
            {
                "sequence": 1,
                "focal": True,
                "coverage": {"reference": f"Coverage/{patient_id}-coverage"},
            }
        ],
        "item": [
            {
                "sequence": 1,
                "productOrService": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "1991302",
                            "display": "semaglutide",
                        }
                    ]
                },
            }
        ],
    }
    return [letter_doc, claim]


def build_todo(findings: list[Finding]) -> list[str]:
    """For a 'missing' decision: what to add to the chart before submitting."""
    return [
        f"{f.criterion} {CRITERION_NAMES[f.criterion]}: {f.reason}"
        for f in findings
        if f.status == "missing"
    ]


def build_reasons(findings: list[Finding]) -> list[str]:
    """For a 'not_met' decision: why the request would not be approved."""
    return [
        f"{f.criterion} {CRITERION_NAMES[f.criterion]}: {f.reason}"
        for f in findings
        if f.status == "not_met"
    ]
