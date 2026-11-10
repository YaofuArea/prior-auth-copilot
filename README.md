# Prior Auth Copilot

A copilot for prior authorization: when a doctor orders a medicine that the insurer must approve first, it reads the patient's chart from a FHIR server, checks it against the payer's coverage criteria, and drafts the request, citing the chart evidence for every criterion. A person reviews the draft before anything is submitted.

The first use case is **semaglutide (a GLP-1 medicine) for type 2 diabetes**, a common and heavily reviewed prior authorization request.

> All patients are synthetic and the payer (Example Health Plan) is fictional. Not for clinical use.

**Status:** work in progress. Done: local FHIR server with test patients, the payer policy, and a rule-based baseline checker.

## Setup

Requires [Docker](https://www.docker.com/) and [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d        # local HAPI FHIR R4 server at http://localhost:8080/fhir (about a minute to start)
uv sync
uv run seed.py              # load the test patients
uv run fhir.py pa-01        # print one patient's chart
uv run criteria.py          # rule-based check of every test patient
uv run criteria.py pa-04    # one patient, with the evidence for each criterion
```

`seed.py` can be run again at any time: every resource has a fixed id, so it updates instead of duplicating. The server keeps data only while its container exists (`docker compose down` deletes it).

## Test cases

Each synthetic patient has a draft semaglutide order. Each case is built around one criterion; pa-03, a weight-loss request, fails several at once, as such a request would in practice:

| Patient | Chart | Expected |
|---|---|---|
| `pa-01` | Type 2 diabetes, A1C 8.4% two months ago, on metformin for over a year | meets all criteria |
| `pa-02` | Type 2 diabetes, A1C 7.8%, never tried metformin | step therapy not met |
| `pa-03` | Obesity only, BMI 33.1, normal A1C | no type 2 diabetes diagnosis |
| `pa-04` | Type 2 diabetes, on metformin, last A1C over a year old | missing recent documentation |
| `pa-05` | Metformin `stopped`; a note says it was stopped for severe diarrhea | meets (intolerance satisfies C4) |
| `pa-06` | On metformin; a note says her mother had medullary thyroid carcinoma | does not meet (C5) |
| `pa-07` | On metformin; a note mentions thyroid carcinoma only to rule it out | meets |

Cases pa-05 to pa-07 can only be decided from the clinical note, stored as a FHIR `DocumentReference` (LOINC `11506-3` progress note). pa-07 is a trap for keyword matching: the note contains "medullary thyroid carcinoma", but negated.

Codes: diagnoses in ICD-10-CM, labs in LOINC (`4548-4` A1C, `39156-5` BMI), medicines in RxNorm (`6809` metformin, `1991302` semaglutide).

## Payer policy and baseline

`data/policy/glp1-t2d.md` is the coverage policy of the fictional Example Health Plan, written in the style of public payer drug policies. Semaglutide is approved when all five criteria hold:

| | Criterion | Where the evidence is |
|---|---|---|
| C1 | Age 18 or older | Patient |
| C2 | Type 2 diabetes diagnosis (ICD-10 E11.x) | Condition |
| C3 | Latest A1C ≥ 7.0%, dated within 180 days | Observation |
| C4 | Metformin for ≥ 90 days, **or** intolerance/contraindication | MedicationRequest, **or clinical notes** |
| C5 | No personal/family history of MTC, no MEN 2 | Condition, **or clinical notes** |

`criteria.py` is the rule-based baseline. It turns each criterion into a check over FHIR data and returns `met`, `not_met` or `missing`, with the FHIR resources it used as evidence. The case decision is `not_met` if any criterion fails, otherwise `missing` if any is undecidable, otherwise `meets`. The rules only see structured data; the parts in bold live in free-text notes, which they cannot read. On the 7 cases:

| Case | Rules | Expected | Why |
|---|---|---|---|
| pa-01 to pa-04 | correct | | everything needed is in coded data |
| pa-05 | not_met | meets | sees a stopped metformin order, not the intolerance in the note |
| pa-06 | **meets** | not_met | cannot see the family history in the note |
| pa-07 | meets | meets | correct, because it ignores notes altogether |

**5/7 correct.** The two errors are not equally bad. pa-05 delays a patient's medicine; pa-06 approves a drug with a boxed warning for someone it may harm. Evaluation should count these two kinds of errors separately. Reading the notes is where an LLM should earn its place.

## Files

| File | What it is |
|---|---|
| `docker-compose.yml` | Local HAPI FHIR server, version pinned |
| `seed.py` | Builds the test patients as FHIR resources and loads them in one transaction |
| `fhir.py` | Small FHIR client: search with paging, and read a patient's conditions, observations, medication requests and notes |
| `data/policy/glp1-t2d.md` | Fictional payer policy for semaglutide in type 2 diabetes |
| `criteria.py` | Rule-based baseline: checks each policy criterion against the chart, with evidence |
