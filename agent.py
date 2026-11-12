"""LLM check of a semaglutide request against policy EHP-RX-0421.

Claude gets the policy text and tools that read the chart from FHIR,
including the clinical notes. It decides each criterion C1-C5 (met /
not_met / missing) and cites the FHIR resources it used. The case decision
is then combined by the same code as the rule baseline (criteria.decide), so
the only difference between the two is how each criterion is judged.

Usage: uv run agent.py pa-05
"""

import json
import sys
from datetime import date
from pathlib import Path

import anthropic
from anthropic import beta_tool

import fhir
from criteria import Finding, decide

MODEL = "claude-opus-5-5"
MAX_TURNS = 15
CRITERIA = ["C1", "C2", "C3", "C4", "C5"]
POLICY = (Path(__file__).parent / "data" / "policy" / "glp1-t2d.md").read_text()

SYSTEM = f"""You check prior authorization requests for a clinic before they are sent to the payer.

Today's date is {date.today().isoformat()}.

Decide each criterion of the policy below as:
- "met": the chart shows the criterion is satisfied.
- "not_met": the chart shows it is not satisfied.
- "missing": the chart does not contain what is needed to decide.

Rules:
- Use the tools to read the chart. Read the clinical notes as well as the coded data: some criteria (such as a metformin intolerance or a family history) may be documented only in a note.
- Judge only from what the tools return. Do not assume facts that are not in the chart.
- In "evidence", list the FHIR references (e.g. "Observation/pa-01-observation-3") exactly as the tools returned them, for every resource your decision relies on.
- In "reason", explain the decision in one or two sentences. When a note is the evidence, quote the sentence that matters.

<policy>
{POLICY}
</policy>"""

# The final answer must match this schema: one finding per criterion.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string", "enum": CRITERIA},
                    "status": {"type": "string", "enum": ["met", "not_met", "missing"]},
                    "reason": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["criterion", "status", "reason", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

# Every FHIR reference the tools returned in the current run, so we can check
# that the evidence Claude cites is something it actually saw.
seen_refs: set[str] = set()


def _result(items: list[dict]) -> str:
    seen_refs.update(item["ref"] for item in items)
    return json.dumps(items)


def _ref(resource: dict) -> str:
    return f"{resource['resourceType']}/{resource['id']}"


def _code(concept: dict) -> dict:
    c = concept["coding"][0]
    return {"code": c["code"], "display": c.get("display", "")}


@beta_tool
def get_patient(patient_id: str) -> str:
    """Get the patient's name, gender and birth date.

    Args:
        patient_id: Patient id, e.g. pa-01.
    """
    p = fhir.get_patient(patient_id)
    name = p["name"][0]
    return _result(
        [
            {
                "ref": _ref(p),
                "name": f"{' '.join(name['given'])} {name['family']}",
                "gender": p["gender"],
                "birth_date": p["birthDate"],
            }
        ]
    )


@beta_tool
def get_conditions(patient_id: str) -> str:
    """Get the patient's diagnoses (ICD-10-CM codes) with status and onset date.

    Args:
        patient_id: Patient id, e.g. pa-01.
    """
    return _result(
        [
            {
                "ref": _ref(c),
                **_code(c["code"]),
                "clinical_status": c["clinicalStatus"]["coding"][0]["code"],
                "onset": c.get("onsetDateTime"),
            }
            for c in fhir.get_conditions(patient_id)
        ]
    )


@beta_tool
def get_observations(patient_id: str, loinc_code: str = "") -> str:
    """Get lab results and vital signs, newest first.

    Args:
        patient_id: Patient id, e.g. pa-01.
        loinc_code: Optional LOINC code to get one test only, e.g. 4548-4 for HbA1c. Leave empty for all.
    """
    return _result(
        [
            {
                "ref": _ref(o),
                **_code(o["code"]),
                "value": o["valueQuantity"]["value"],
                "unit": o["valueQuantity"]["unit"],
                "date": o["effectiveDateTime"],
            }
            for o in fhir.get_observations(patient_id, loinc_code or None)
        ]
    )


@beta_tool
def get_medication_requests(patient_id: str) -> str:
    """Get the patient's prescriptions (RxNorm codes) with status and date written.

    Status "active" means currently prescribed, "stopped" means discontinued,
    "draft" means not yet signed (such as an order awaiting prior authorization).

    Args:
        patient_id: Patient id, e.g. pa-01.
    """
    return _result(
        [
            {
                "ref": _ref(m),
                **_code(m["medicationCodeableConcept"]),
                "status": m["status"],
                "authored_on": m["authoredOn"],
            }
            for m in fhir.get_medication_requests(patient_id)
        ]
    )


@beta_tool
def get_notes(patient_id: str) -> str:
    """Get the patient's clinical notes (free text), newest first.

    Args:
        patient_id: Patient id, e.g. pa-01.
    """
    return _result(fhir.get_notes(patient_id))


TOOLS = [
    get_patient,
    get_conditions,
    get_observations,
    get_medication_requests,
    get_notes,
]


def assess(patient_id: str) -> tuple[str, list[Finding], list[str]]:
    """Returns (decision, findings, cited references the tools never returned)."""
    seen_refs.clear()
    runner = anthropic.Anthropic().beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        tools=TOOLS,
        messages=[
            {
                "role": "user",
                "content": f"Check the draft semaglutide order MedicationRequest/{patient_id}-order for patient {patient_id}.",
            }
        ],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        max_iterations=MAX_TURNS,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    final = runner.until_done()
    if final.stop_reason == "refusal":
        raise RuntimeError(f"{patient_id}: declined by safety classifier")

    text = "".join(b.text for b in final.content if b.type == "text")
    findings = [Finding(**f) for f in json.loads(text)["findings"]]

    # The schema allows any list of findings; we need each criterion exactly once.
    got = sorted(f.criterion for f in findings)
    if got != CRITERIA:
        raise ValueError(f"{patient_id}: expected one finding per criterion, got {got}")

    unseen = [e for f in findings for e in f.evidence if e not in seen_refs]
    return decide(findings), findings, unseen


if __name__ == "__main__":
    patient_id = sys.argv[1] if len(sys.argv) > 1 else "pa-05"
    decision, findings, unseen = assess(patient_id)
    print(f"{patient_id}: {decision}")
    for f in findings:
        print(f"  {f.criterion} {f.status:8} {f.reason}")
        for e in f.evidence:
            print(f"              {e}")
    if unseen:
        print(f"\nCited but never returned by a tool: {unseen}")
