"""Web API for the copilot, used by the React front end in web/.

  GET  /api/cases                  the test cases
  GET  /api/cases/{id}/chart       the patient's chart, as the agent sees it
  POST /api/cases/{id}/assess      findings, decision and draft
  POST /api/cases/{id}/submit      write the request to FHIR (needs attestation)

Assessments come from the last evaluate.py run (results/agent_runs.json) by
default, so the public demo costs nothing. A live run calls Claude and needs
the passcode in DEMO_PASSCODE; live runs are also capped per day.

Usage: uv run uvicorn api:app --reload    (API docs at http://localhost:8000/docs)
"""

import json
import os
import secrets
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import draft
import fhir
import review
import seed
from criteria import Finding, decide

RESULTS = Path(__file__).parent / "results" / "agent_runs.json"
DEMO_PASSCODE = os.environ.get("DEMO_PASSCODE", "")  # empty: live runs disabled
LIVE_RUNS_PER_DAY = int(os.environ.get("LIVE_RUNS_PER_DAY", "20"))

CASES = {case[0]: case for case in seed.CASES}
TEST_IDS = {case[0] for case in seed.TEST_CASES}
SAVED = json.loads(RESULTS.read_text())
SAVED_RUNS = {run["case"]: run for run in SAVED["runs"]}

# The latest assessment of each case. Submit uses this, never findings sent by
# the browser, so a client cannot submit a request the agent did not approve.
latest: dict[str, list[Finding]] = {}

# One live run at a time: agent.seen_refs is shared state, and a demo does
# not need parallel runs. The lock also guards the daily counter.
live_lock = threading.Lock()
live_runs = {"day": date.today(), "count": 0}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Case dates are relative to the day they are loaded (see evaluate.py).
    seed.main()
    yield


app = FastAPI(title="Prior Auth Copilot", lifespan=lifespan)


def check_case(patient_id: str) -> None:
    if patient_id not in CASES:
        raise HTTPException(404, f"Unknown case {patient_id}")


@app.get("/api/cases")
def list_cases() -> list[dict]:
    return [
        {
            "id": pid,
            "name": f"{given} {family}",
            "scenario": why,
            "expected": expected,
            "split": "test" if pid in TEST_IDS else "dev",
        }
        for pid, (family, given), _birth, _gender, (expected, why), _facts in seed.CASES
    ]


@app.get("/api/cases/{patient_id}/chart")
def chart(patient_id: str) -> dict:
    check_case(patient_id)
    return {
        "patient": fhir.patient_view(patient_id),
        "conditions": fhir.conditions_view(patient_id),
        "observations": fhir.observations_view(patient_id),
        "medications": fhir.medications_view(patient_id),
        "notes": fhir.get_notes(patient_id),
    }


class AssessRequest(BaseModel):
    live: bool = False
    passcode: str = ""


def run_live(patient_id: str, passcode: str) -> tuple[list[Finding], list[str]]:
    if not DEMO_PASSCODE:
        raise HTTPException(403, "Live runs are turned off on this server")
    if not secrets.compare_digest(passcode.encode(), DEMO_PASSCODE.encode()):
        raise HTTPException(403, "Wrong passcode")
    with live_lock:
        if live_runs["day"] != date.today():
            live_runs.update(day=date.today(), count=0)
        if live_runs["count"] >= LIVE_RUNS_PER_DAY:
            raise HTTPException(429, "Daily limit of live runs reached")
        live_runs["count"] += 1

        import agent  # needs ANTHROPIC_API_KEY, so only imported for live runs

        try:
            _decision, findings, unseen = agent.assess(patient_id)
        except anthropic.APIError as e:
            raise HTTPException(502, f"Claude API error: {e}") from e
    return findings, unseen


@app.post("/api/cases/{patient_id}/assess")
def assess(patient_id: str, request: AssessRequest) -> dict:
    check_case(patient_id)
    if request.live:
        findings, unseen = run_live(patient_id, request.passcode)
        source = "live run"
    else:
        run = SAVED_RUNS[patient_id]
        findings = [Finding(**f) for f in run["findings"]]
        unseen = run["cited_but_unseen"]
        source = f"saved run of {SAVED['run_at'][:10]}"

    latest[patient_id] = findings
    decision = decide(findings)
    result = {
        "decision": decision,
        "source": source,
        "model": SAVED["model"],
        "findings": [asdict(f) for f in findings],
        "cited_but_unseen": unseen,
    }
    if decision == "meets":
        result["letter"] = draft.build_letter(fhir.get_patient(patient_id), findings)
        result["attestation"] = draft.ATTESTATION
    elif decision == "missing":
        result["todo"] = draft.build_todo(findings)
    else:
        result["reasons"] = draft.build_reasons(findings)
    return result


class SubmitRequest(BaseModel):
    attest: bool


@app.post("/api/cases/{patient_id}/submit")
def submit(patient_id: str, request: SubmitRequest) -> dict:
    check_case(patient_id)
    if not request.attest:
        raise HTTPException(400, "The prescriber must give the C5 attestation")
    findings = latest.get(patient_id)
    if findings is None:
        raise HTTPException(409, "Assess the case before submitting")
    if decide(findings) != "meets":
        raise HTTPException(409, "Only a case that meets the policy can be submitted")

    letter = draft.build_letter(fhir.get_patient(patient_id), findings)
    review.submit(draft.build_request(patient_id, findings, letter))
    # Read the Claim back, so the page shows what the server actually stored.
    claim = fhir.client.get(f"Claim/{draft.claim_id(patient_id)}")
    claim.raise_for_status()
    return {
        "claim": claim.json(),
        "letter_ref": f"DocumentReference/{draft.letter_id(patient_id)}",
    }
