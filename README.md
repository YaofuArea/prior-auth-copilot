# Prior Auth Copilot

A copilot for prior authorization: when a doctor orders a medicine that the insurer must approve first, it reads the patient's chart from a FHIR server, checks it against the payer's coverage criteria, and drafts the request, citing the chart evidence for every criterion. A person reviews the draft before anything is submitted.

The first use case is **semaglutide (a GLP-1 medicine) for type 2 diabetes**, a common and heavily reviewed prior authorization request.

> All patients are synthetic and the payer (Example Health Plan) is fictional. Not for clinical use.

**Status:** work in progress. Done: local FHIR server with 15 test cases, the payer policy, a rule-based baseline, an LLM agent that reads the chart including clinical notes, and a review step that drafts the request and writes it to FHIR only after the doctor signs. Next: a web demo and deployment.

## Results so far

| | Dev cases (7) | Test cases (8) | False approvals | False denials |
|---|---|---|---|---|
| Rule baseline (`criteria.py`) | 5/7 | 6/8 | 1 | 3 |
| LLM agent (`agent.py`, Claude Opus 5.5) | 7/7 | **8/8** | 0 | 0 |

The rules fail exactly where the evidence is only in a clinical note. The agent decided every case correctly, and every FHIR reference it cited was one its tools had actually returned. This is one run on 15 small cases; see [Limitations](#limitations).

## How it works

```
                 ┌─ tools: patient, conditions, labs, medications, notes ─┐
FHIR server ─────┤                                                        ├──▶ C1..C5: met / not_met / missing
(HAPI, local)    └──────────────────────── Claude ────────────────────────┘      + reason + cited FHIR resources
                                             ▲                                              │
payer policy (Markdown) ─────────────────────┘                                              ▼
                                                                         decide(): not_met > missing > meets
```

1. Claude gets the payer policy and five tools that read the chart from FHIR, including free-text notes.
2. For each criterion it returns `met`, `not_met` or `missing`, a short reason (quoting the note when a note is the evidence), and the FHIR references it relied on. The output is constrained by a JSON schema.
3. Code, not the model, checks that every criterion was answered once and that every cited reference was actually returned by a tool, then combines the findings into one decision with the same function the rule baseline uses. So the only difference between the two is how each criterion is judged.

The decision rule: any `not_met` makes the case `not_met`, even if something else is missing (a new A1C will not fix a missing diagnosis); otherwise any `missing` makes it `missing`; otherwise `meets`.

### From decision to request

`review.py` turns the decision into what the clinic acts on:

| Decision | Output |
|---|---|
| `meets` | A draft prior authorization request and a letter of medical necessity, shown for review |
| `missing` | A to-do list, e.g. "need an HbA1c from the last 180 days" |
| `not_met` | The reasons the request would not be approved |

The request is a FHIR `Claim` with `use: "preauthorization"`, the resource the Da Vinci Prior Authorization Support (PAS) guide builds on. Every FHIR resource the agent cited is attached as `supportingInfo`, labeled with the criterion it supports, and the letter is attached as a `DocumentReference`. The letter is assembled from the agent's checked reasons and citations rather than written by a second LLM call, so it cannot contain claims that were never evaluated.

**Nothing is written until the doctor types `sign`.** Signing also gives the C5 attestation (no history of medullary thyroid carcinoma or MEN 2), which the policy requires from the prescriber; an AI cannot attest for them. The letter and the Claim are then written in one FHIR transaction, so either both are stored or neither is.

## Setup

### Run everything with Docker

Requires only [Docker](https://www.docker.com/).

```bash
docker compose up -d --build     # FHIR server + app; open http://localhost:8000
```

The app waits for the FHIR server, loads the test patients, and serves both the web page and the API. Without further setup it shows the agent's saved results. To allow live agent runs, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` and `DEMO_PASSCODE` before starting.

### Development

Requires [Docker](https://www.docker.com/), [uv](https://docs.astral.sh/uv/), and an Anthropic API key for the agent.

```bash
docker compose up -d fhir   # only the HAPI FHIR R4 server, at http://localhost:8080/fhir (about a minute to start)
uv sync
uv run seed.py              # load the test patients
uv run fhir.py pa-05        # print one patient's chart, including notes
uv run criteria.py          # rule baseline on every case (no API key needed)
uv run criteria.py pa-04    # one case, with the evidence for each criterion

export ANTHROPIC_API_KEY=...
uv run agent.py pa-05       # LLM agent on one case
uv run evaluate.py          # rules vs agent on all 15 cases (15 API calls)

uv run review.py pa-01           # agent + draft request; type "sign" to submit (one API call)
uv run review.py pa-01 --saved   # same, reusing the findings saved by evaluate.py (free)

uv run uvicorn api:app --reload  # web API; interactive docs at http://localhost:8000/docs
uv run pytest                    # API tests (need the FHIR server; no Claude calls)
```

### Web app

Requires [Node.js](https://nodejs.org/) 22 or later. With the API running (`uv run uvicorn api:app --reload`), in a second terminal:

```bash
cd web
npm install
npm run dev                      # http://localhost:5173 (forwards /api to the API on port 8000)
```

Pick a case to see the chart, then show the agent's result. Hovering a cited record in a finding highlights it in the chart, and every chart record shows which criteria cite it. For a case that meets the policy, the page shows the draft letter; the request is written to FHIR only after the prescriber checks the attestation and signs.

The web API serves saved agent results by default, so a public demo costs nothing. Live runs call Claude only with the passcode set in `DEMO_PASSCODE`, and are capped at `LIVE_RUNS_PER_DAY` (default 20). Submitting uses the server's own latest assessment of the case, never findings sent by the browser.

`seed.py` can be run again at any time: every resource has a fixed id, so it updates instead of duplicating. Case dates are relative to the day it runs (e.g. "A1C from 170 days ago"), so `evaluate.py` reseeds first. The server keeps data only while its container exists (`docker compose down` deletes it).

## Payer policy

`data/policy/glp1-t2d.md` is the coverage policy of the fictional Example Health Plan, written in the style of public payer drug policies. Semaglutide is approved when all five criteria hold:

| | Criterion | Where the evidence is |
|---|---|---|
| C1 | Age 18 or older | Patient |
| C2 | Type 2 diabetes diagnosis (ICD-10 E11.x) | Condition |
| C3 | Latest A1C ≥ 7.0%, dated within 180 days | Observation |
| C4 | Metformin for ≥ 90 days, **or** intolerance/contraindication | MedicationRequest, **or clinical notes** |
| C5 | No personal/family history of medullary thyroid carcinoma (MTC), no MEN 2 | Condition, **or clinical notes** |

The rule baseline only sees coded data; the parts in bold can live in free-text notes.

## Test cases

Each synthetic patient has a draft semaglutide order. Notes are stored as FHIR `DocumentReference` resources (LOINC `11506-3` progress note). Codes: ICD-10-CM for diagnoses, LOINC for labs (`4548-4` A1C, `39156-5` BMI), RxNorm for medicines (`6809` metformin, `1991302` semaglutide).

**Development cases** were used while building both checkers and clarifying the policy, so results on them are optimistic.

| Case | Chart | Expected | Rules | Agent |
|---|---|---|---|---|
| pa-01 | Type 2 diabetes, A1C 8.4%, on metformin over a year | meets | ✓ | ✓ |
| pa-02 | Type 2 diabetes, A1C 7.8%, never tried metformin | not_met | ✓ | ✓ |
| pa-03 | Obesity only, BMI 33.1, normal A1C (weight-loss request) | not_met | ✓ | ✓ |
| pa-04 | On metformin, last A1C over a year old | missing | ✓ | ✓ |
| pa-05 | Metformin `stopped`; note: stopped for severe diarrhea | meets | ✗ not_met | ✓ |
| pa-06 | On metformin; note: mother had MTC | not_met | ✗ **meets** | ✓ |
| pa-07 | Note mentions MTC only to rule it out (keyword trap) | meets | ✓ | ✓ |

**Test cases** were written, with their expected decisions, after the policy was clarified and before the agent was ever run on them. The commit with these labels ([`bf169dd`](https://github.com/YaofuArea/prior-auth-copilot/commit/bf169dd)) comes before the run.

| Case | What it tests | Expected | Rules | Agent |
|---|---|---|---|---|
| pa-08 | Metformin for only 60 days | not_met | ✓ | ✓ |
| pa-09 | A1C exactly 7.0%, 170 days old (both boundaries) | meets | ✓ | ✓ |
| pa-10 | No metformin; note: eGFR 24, metformin contraindicated | meets | ✗ not_met | ✓ |
| pa-11 | Latest A1C 6.6%; note mentions 8.5% from last year | not_met | ✓ | ✓ |
| pa-12 | Type 1 diabetes | not_met | ✓ | ✓ |
| pa-13 | Thyroid cancer code (C73); note: papillary, not medullary | meets | ✗ not_met | ✓ |
| pa-14 | Stopped metformin because she dislikes pills, no side effects | not_met | ✓ | ✓ |
| pa-15 | No A1C on file at all | missing | ✓ | ✓ |

pa-13 shows a limit of codes themselves: ICD-10 has no code for medullary thyroid carcinoma, so a rule can only see "thyroid cancer" and must either over-exclude (as here) or ignore thyroid cancer entirely. The agent read the note and cited it: *"History of papillary thyroid cancer ... No family history of medullary thyroid carcinoma or MEN 2."* In pa-14 it separated a preference from an intolerance: *"the note describes a preference, not an intolerance or contraindication."*

Full agent output for every case, with reasons and citations: [`results/agent_runs.json`](results/agent_runs.json).

## What I learned

- **Count error types separately.** A false approval and a false denial are not equally bad. In pa-06, the rules would mark a drug with a boxed warning as approvable for a patient whose mother had the cancer it warns about; a false denial "only" delays a medicine. A single accuracy number hides that.
- **The agent found an ambiguity in my own policy.** In the first run (policy v1.0, [`results/agent_runs_policy_v1.json`](results/agent_runs_policy_v1.json)) the agent got only 4/7 dev cases right, with no false approvals. Every error came from one question: what does a chart that says *nothing* mean? The policy asked for an "attestation" of no thyroid cancer history, so the agent marked C5 `missing` whenever the chart was silent; my rules and labels had assumed silence meant "no history". Likewise for a chart with no metformin and no note, the agent said `missing` while my labels said `not_met`. The agent's reading was defensible, so I fixed the policy, not the agent: v1.1 says the prescriber attests to C5 on the request form (the review looks only for contrary evidence), and no metformin trial means not met. The system prompt did not change.
- **Changing the spec after seeing results is close to tuning on the test set.** That is why the 8 test cases were written and committed only after v1.1, before running the agent on them.
- **The model, not the code, decides each criterion; the code decides the case.** Keeping the combining rule in code makes the agent and the baseline directly comparable, and means a model can never "approve" while one of its own findings says `not_met`.

## Limitations

- **15 cases, written by me.** I designed the cases knowing how both checkers work, and each tests one thing in a short, clean note. Real notes are long, contradictory and full of abbreviations. 8/8 on the test set shows the approach works on clear cases, not that it is reliable.
- **One run.** An LLM can answer differently each time. Running each case several times would show how stable the decisions are.
- **Submission stops at our own FHIR server.** A real request would go to the payer's prior authorization API (the Da Vinci PAS workflow), which also requires PAS-specific profiles this Claim does not follow.
- **The letter reads like a review.** Its sentences are the agent's reasons, which explain the decision ("the most recent HbA1c is 8.4% ... within 180 days") rather than argue for the patient as a doctor would. With `--saved`, the reasons also mention the date of that evaluation run.
- **One policy, one drug.** The whole policy fits in the prompt, so no retrieval is needed yet. With many payers and drugs, the relevant policy would have to be retrieved first.

## Files

| File | What it is |
|---|---|
| `docker-compose.yml` | The FHIR server (HAPI, version pinned) and the app |
| `Dockerfile` | Two stages: builds the web app with Node, then a Python image that serves it and the API as a non-root user |
| `seed.py` | The 15 test cases, the payer, the prescriber and each patient's coverage, loaded in one transaction |
| `fhir.py` | Small FHIR client: search with paging; read conditions, observations, medication requests and notes |
| `data/policy/glp1-t2d.md` | Fictional payer policy (v1.1, with revision history) |
| `criteria.py` | Rule-based baseline, and `decide()`, the rule that combines findings into a decision |
| `agent.py` | LLM agent: Claude with FHIR tools, schema-constrained findings, citation check |
| `evaluate.py` | Rules vs agent on all cases, errors by type, dev and test reported separately |
| `draft.py` | Builds the FHIR Claim and letter for `meets`, the to-do list for `missing`, the reasons for `not_met` |
| `review.py` | Human review: shows the findings and draft, and writes to FHIR only after the doctor signs |
| `api.py` | FastAPI web API: cases, chart, assess (saved or live with passcode), submit |
| `web/` | React + TypeScript front end (Vite): case list, chart with cited records highlighted, findings, sign and submit |
| `tests/test_api.py` | API tests, including every refusal path (no attestation, case not met, wrong passcode, daily limit) |
| `results/` | Saved agent output for each evaluation run |
