"""Review a prior authorization case and, if approved by a person, submit it.

Runs the agent on one case and shows its findings. Then:
- meets:    shows the draft request and letter. Nothing is written until the
            doctor types "sign", which also gives the C5 attestation that the
            policy requires from the prescriber (an AI cannot attest for them).
            On "sign", the letter and the Claim are written to FHIR together.
- missing:  shows what to add to the chart first.
- not_met:  shows why the request would not be approved.

Usage: uv run review.py pa-01           (runs the agent: one API call)
       uv run review.py pa-01 --saved   (reuses findings from the last evaluate.py run; free)
"""

import json
import sys
from pathlib import Path

import draft
import fhir
from criteria import Finding, decide

RESULTS = Path(__file__).parent / "results" / "agent_runs.json"


def saved_findings(patient_id: str) -> list[Finding]:
    runs = json.loads(RESULTS.read_text())["runs"]
    run = next((r for r in runs if r["case"] == patient_id), None)
    if run is None:
        raise SystemExit(f"{patient_id} is not in {RESULTS.name}; run without --saved")
    return [Finding(**f) for f in run["findings"]]


def submit(resources: list[dict]) -> None:
    """Write the letter and the Claim in one transaction: both or neither."""
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": r,
                "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"},
            }
            for r in resources
        ],
    }
    fhir.client.post("", json=bundle).raise_for_status()


def main() -> None:
    patient_id = sys.argv[1] if len(sys.argv) > 1 else "pa-01"
    if "--saved" in sys.argv:
        findings = saved_findings(patient_id)
    else:
        import agent  # only needed (and only needs an API key) for a fresh run

        _decision, findings, unseen = agent.assess(patient_id)
        if unseen:
            raise SystemExit(f"Agent cited resources it never saw: {unseen}")
    decision = decide(findings)

    print(f"{patient_id}: {decision}\n")
    for f in findings:
        print(f"  {f.criterion} {f.status:8} {f.reason}")

    if decision == "not_met":
        print("\nNot submittable. The request would not be approved because:")
        for line in draft.build_reasons(findings):
            print(f"  - {line}")
        return
    if decision == "missing":
        print("\nBefore submitting, add to the chart:")
        for line in draft.build_todo(findings):
            print(f"  - {line}")
        return

    letter = draft.build_letter(fhir.get_patient(patient_id), findings)
    resources = draft.build_request(patient_id, findings, letter)
    claim = resources[1]
    print("\n--- Draft letter of medical necessity ---\n")
    print(letter)
    print("\n--- Draft prior authorization request (FHIR Claim) ---\n")
    print(f"  use: {claim['use']}, insurer: {claim['insurer']['reference']}")
    print(f"  prescription: {claim['prescription']['reference']}")
    print(f"  {len(claim['supportingInfo'])} supporting records attached")

    print(
        f"\nTyping 'sign' submits this request and makes this attestation:\n  {draft.ATTESTATION}"
    )
    if input("> ").strip().lower() != "sign":
        print("Not submitted.")
        return
    submit(resources)
    print(
        f"Submitted: Claim/{draft.claim_id(patient_id)}, DocumentReference/{draft.letter_id(patient_id)}"
    )


if __name__ == "__main__":
    main()
