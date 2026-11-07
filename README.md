# Prior Auth Copilot

A copilot for prior authorization: when a doctor orders a medicine that the insurer must approve first, it reads the patient's chart from a FHIR server, checks it against the payer's coverage criteria, and drafts the request, citing the chart evidence for every criterion. A person reviews the draft before anything is submitted.

The first use case is **semaglutide (a GLP-1 medicine) for type 2 diabetes**, a common and heavily reviewed prior authorization request.

> All patients are synthetic and the payer policy will be fictional. Not for clinical use.

**Status:** work in progress. Step 1 (local FHIR server with test patients) is done.

## Setup

Requires [Docker](https://www.docker.com/) and [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d        # local HAPI FHIR R4 server at http://localhost:8080/fhir (about a minute to start)
uv sync
uv run seed.py              # load the test patients
uv run fhir.py pa-01        # print one patient's chart
```

`seed.py` can be run again at any time: every resource has a fixed id, so it updates instead of duplicating. The server keeps data only while its container exists (`docker compose down` deletes it).

## Test cases

Each synthetic patient has a draft semaglutide order and differs from the others in one thing, so each tests one criterion:

| Patient | Chart | Expected |
|---|---|---|
| `pa-01` | Type 2 diabetes, A1C 8.4% two months ago, on metformin for over a year | meets all criteria |
| `pa-02` | Type 2 diabetes, A1C 7.8%, never tried metformin | step therapy not met |
| `pa-03` | Obesity only, BMI 33.1, normal A1C | no type 2 diabetes diagnosis |
| `pa-04` | Type 2 diabetes, on metformin, last A1C over a year old | missing recent documentation |

Codes: diagnoses in ICD-10-CM, labs in LOINC (`4548-4` A1C, `39156-5` BMI), medicines in RxNorm (`6809` metformin, `1991302` semaglutide).

## Files

| File | What it is |
|---|---|
| `docker-compose.yml` | Local HAPI FHIR server, version pinned |
| `seed.py` | Builds the test patients as FHIR resources and loads them in one transaction |
| `fhir.py` | Small FHIR client: search with paging, and read a patient's conditions, observations and medication requests |
