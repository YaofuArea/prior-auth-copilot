"""Rule-based check of a semaglutide request against policy EHP-RX-0421.

Each criterion in data/policy/glp1-t2d.md (C1-C5) becomes a function that
reads the patient's chart from FHIR and returns a Finding:
  met      the chart shows the criterion is satisfied
  not_met  the chart shows it is not
  missing  the chart does not have what is needed to decide
plus the FHIR resources used as evidence.

This is the baseline: it only sees structured data (codes, lab values, dates).
Parts of the policy that live in free-text notes, such as a metformin
intolerance (C4) or a family history of thyroid cancer (C5), are invisible
to it.

Usage: uv run criteria.py          (check every test patient)
       uv run criteria.py pa-02    (check one patient, with details)
"""

import sys
from dataclasses import dataclass, field
from datetime import date

from fhir import (
    get_conditions,
    get_medication_requests,
    get_observations,
    get_patient,
)

A1C_LOINC = "4548-4"
METFORMIN_RXNORM = "6809"
A1C_THRESHOLD = 7.0  # percent (C3)
A1C_MAX_AGE_DAYS = 180  # (C3)
METFORMIN_MIN_DAYS = 90  # (C4)
# C5: thyroid cancer (C73) and MEN 2A / 2B. ICD-10 has no code just for MTC.
EXCLUSION_ICD10 = {"C73", "E31.22", "E31.23"}


@dataclass
class Finding:
    criterion: str
    status: str  # "met", "not_met" or "missing"
    reason: str
    evidence: list[str] = field(
        default_factory=list
    )  # e.g. "Observation/pa-01-observation-3"


def ref(resource: dict) -> str:
    return f"{resource['resourceType']}/{resource['id']}"


def code_of(concept: dict) -> str:
    return concept["coding"][0]["code"]


def days_since(iso_date: str, today: date) -> int:
    return (today - date.fromisoformat(iso_date[:10])).days


def check_age(patient: dict, today: date) -> Finding:
    born = date.fromisoformat(patient["birthDate"])
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    status = "met" if age >= 18 else "not_met"
    return Finding("C1", status, f"age {age}", [ref(patient)])


def check_diagnosis(conditions: list[dict]) -> Finding:
    t2d = [
        c
        for c in conditions
        if code_of(c["code"]).startswith("E11")
        and code_of(c["clinicalStatus"]) == "active"
    ]
    if t2d:
        return Finding(
            "C2", "met", "active type 2 diabetes diagnosis", [ref(c) for c in t2d]
        )
    return Finding("C2", "not_met", "no active E11.x diagnosis on the problem list")


def check_a1c(a1c_results: list[dict], today: date) -> Finding:
    if not a1c_results:
        return Finding("C3", "missing", "no A1C result on file")
    latest = a1c_results[0]  # get_observations returns newest first
    value = latest["valueQuantity"]["value"]
    age_days = days_since(latest["effectiveDateTime"], today)
    if age_days > A1C_MAX_AGE_DAYS:
        return Finding(
            "C3",
            "missing",
            f"latest A1C ({value}%) is {age_days} days old; need one from the last {A1C_MAX_AGE_DAYS} days",
            [ref(latest)],
        )
    status = "met" if value >= A1C_THRESHOLD else "not_met"
    return Finding(
        "C3", status, f"A1C {value}% from {age_days} days ago", [ref(latest)]
    )


def check_metformin(medication_requests: list[dict], today: date) -> Finding:
    metformin = [
        m
        for m in medication_requests
        if code_of(m["medicationCodeableConcept"]) == METFORMIN_RXNORM
        and m["status"] in ("active", "completed")
    ]
    if not metformin:
        return Finding(
            "C4",
            "not_met",
            "no metformin on the medication list (an intolerance in the notes would also qualify, but rules cannot read notes)",
        )
    longest = max(metformin, key=lambda m: days_since(m["authoredOn"], today))
    days = days_since(longest["authoredOn"], today)
    status = "met" if days >= METFORMIN_MIN_DAYS else "not_met"
    return Finding(
        "C4", status, f"metformin prescribed {days} days ago", [ref(longest)]
    )


def check_exclusions(conditions: list[dict]) -> Finding:
    excluded = [c for c in conditions if code_of(c["code"]) in EXCLUSION_ICD10]
    if excluded:
        return Finding(
            "C5",
            "not_met",
            "thyroid cancer or MEN 2 on the problem list",
            [ref(c) for c in excluded],
        )
    return Finding(
        "C5",
        "met",
        "no thyroid cancer or MEN 2 on the problem list (family history is only in notes)",
    )


def check_patient(
    patient_id: str, today: date | None = None
) -> tuple[str, list[Finding]]:
    """Check every criterion and combine them into one decision."""
    today = today or date.today()
    conditions = get_conditions(patient_id)
    findings = [
        check_age(get_patient(patient_id), today),
        check_diagnosis(conditions),
        check_a1c(get_observations(patient_id, A1C_LOINC), today),
        check_metformin(get_medication_requests(patient_id), today),
        check_exclusions(conditions),
    ]
    return decide(findings), findings


def decide(findings: list[Finding]) -> str:
    """Combine per-criterion findings into one case decision."""
    statuses = {f.status for f in findings}
    # A failed criterion decides the case even if something else is missing:
    # a new A1C will not fix a missing diagnosis.
    if "not_met" in statuses:
        return "not_met"
    if "missing" in statuses:
        return "missing"
    return "meets"


def main() -> None:
    if len(sys.argv) > 1:
        decision, findings = check_patient(sys.argv[1])
        print(f"{sys.argv[1]}: {decision}")
        for f in findings:
            print(f"  {f.criterion} {f.status:8} {f.reason}")
            for e in f.evidence:
                print(f"              {e}")
        return

    from seed import CASES  # expected decisions for the test patients

    correct = 0
    for pid, _name, _birth, _gender, (expected, why), _facts in CASES:
        decision, findings = check_patient(pid)
        correct += decision == expected
        failing = ", ".join(
            f"{f.criterion} {f.status}" for f in findings if f.status != "met"
        )
        mark = "ok  " if decision == expected else "MISS"
        print(f"{mark} {pid}: got {decision:8} expected {expected:8} {failing}")
    print(f"\n{correct}/{len(CASES)} decisions match")


if __name__ == "__main__":
    main()
