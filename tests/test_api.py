"""API tests. They use the local FHIR server (docker compose up -d) and the
saved agent results; no Claude API calls are made.

Usage: uv run pytest
"""

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture(scope="module")
def client():
    with TestClient(api.app) as c:  # runs the startup seeding
        yield c


@pytest.fixture
def passcode(monkeypatch):
    monkeypatch.setattr(api, "DEMO_PASSCODE", "right-code")
    monkeypatch.setitem(api.live_runs, "count", 0)
    return "right-code"


def test_lists_all_cases(client):
    cases = client.get("/api/cases").json()
    assert len(cases) == 15
    assert {c["split"] for c in cases} == {"dev", "test"}


def test_chart_excludes_the_copilots_own_letter(client):
    notes = client.get("/api/cases/pa-05/chart").json()["notes"]
    assert [n["ref"] for n in notes] == ["DocumentReference/pa-05-note-4"]


def test_unknown_case(client):
    assert client.get("/api/cases/pa-99/chart").status_code == 404


@pytest.mark.parametrize(
    "case, decision, output",
    [
        ("pa-05", "meets", "letter"),
        ("pa-04", "missing", "todo"),
        ("pa-06", "not_met", "reasons"),
    ],
)
def test_saved_assessment(client, case, decision, output):
    result = client.post(f"/api/cases/{case}/assess", json={}).json()
    assert result["decision"] == decision
    assert output in result


def test_submit_requires_assessment(client):
    api.latest.pop("pa-09", None)
    assert (
        client.post("/api/cases/pa-09/submit", json={"attest": True}).status_code == 409
    )


def test_submit_requires_attestation(client):
    client.post("/api/cases/pa-05/assess", json={})
    assert (
        client.post("/api/cases/pa-05/submit", json={"attest": False}).status_code
        == 400
    )


def test_cannot_submit_a_case_that_does_not_meet(client):
    client.post("/api/cases/pa-06/assess", json={})
    assert (
        client.post("/api/cases/pa-06/submit", json={"attest": True}).status_code == 409
    )


def test_submit_writes_claim(client):
    client.post("/api/cases/pa-05/assess", json={})
    response = client.post("/api/cases/pa-05/submit", json={"attest": True})
    assert response.status_code == 200
    claim = response.json()["claim"]
    assert claim["use"] == "preauthorization"
    refs = [s["valueReference"]["reference"] for s in claim["supportingInfo"]]
    assert "DocumentReference/pa-05-note-4" in refs  # the intolerance note


def test_live_run_disabled_without_passcode(client, monkeypatch):
    monkeypatch.setattr(api, "DEMO_PASSCODE", "")
    response = client.post(
        "/api/cases/pa-01/assess", json={"live": True, "passcode": "x"}
    )
    assert response.status_code == 403


def test_live_run_wrong_passcode(client, passcode):
    response = client.post(
        "/api/cases/pa-01/assess", json={"live": True, "passcode": "nope"}
    )
    assert response.status_code == 403


def test_live_run_daily_limit(client, passcode, monkeypatch):
    monkeypatch.setitem(api.live_runs, "count", api.LIVE_RUNS_PER_DAY)
    response = client.post(
        "/api/cases/pa-01/assess", json={"live": True, "passcode": passcode}
    )
    assert response.status_code == 429
