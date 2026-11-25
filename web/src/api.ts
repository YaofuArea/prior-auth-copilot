// Types and calls for the FastAPI backend (api.py). Each type mirrors what
// one endpoint returns.

export type Decision = 'meets' | 'not_met' | 'missing'
export type Status = 'met' | 'not_met' | 'missing'

export interface CaseSummary {
  id: string
  name: string
  scenario: string
  expected: Decision
  split: 'dev' | 'test'
}

export interface Patient {
  ref: string
  name: string
  gender: string
  birth_date: string
}

export interface Condition {
  ref: string
  code: string
  display: string
  clinical_status: string
  onset: string | null
}

export interface Observation {
  ref: string
  code: string
  display: string
  value: number
  unit: string
  date: string
}

export interface Medication {
  ref: string
  code: string
  display: string
  status: string
  authored_on: string
}

export interface Note {
  ref: string
  date: string
  text: string
}

export interface Chart {
  patient: Patient
  conditions: Condition[]
  observations: Observation[]
  medications: Medication[]
  notes: Note[]
}

export interface Finding {
  criterion: string
  status: Status
  reason: string
  evidence: string[] // FHIR references, e.g. "Observation/pa-01-observation-3"
}

export interface Assessment {
  decision: Decision
  source: string
  model: string
  findings: Finding[]
  cited_but_unseen: string[]
  letter?: string
  attestation?: string
  todo?: string[]
  reasons?: string[]
}

export interface Claim {
  id: string
  use: string
  status: string
  created: string
  supportingInfo: {
    sequence: number
    category: { text: string }
    valueReference: { reference: string }
  }[]
}

export interface SubmitResult {
  claim: Claim
  letter_ref: string
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    // FastAPI puts the reason for an HTTPException in "detail".
    let message = `${response.status} ${response.statusText}`
    try {
      message = (await response.json()).detail ?? message
    } catch {
      // not JSON; keep the status text
    }
    throw new Error(message)
  }
  return response.json()
}

export const api = {
  cases: () => request<CaseSummary[]>('/api/cases'),
  chart: (id: string) => request<Chart>(`/api/cases/${id}/chart`),
  assess: (id: string, live: boolean, passcode: string) =>
    request<Assessment>(`/api/cases/${id}/assess`, { live, passcode }),
  submit: (id: string) =>
    request<SubmitResult>(`/api/cases/${id}/submit`, { attest: true }),
}

export const DECISION_LABEL: Record<Decision, string> = {
  meets: 'Meets policy',
  not_met: 'Does not meet policy',
  missing: 'Missing documentation',
}

export const STATUS_LABEL: Record<Status, string> = {
  met: 'Met',
  not_met: 'Not met',
  missing: 'Missing',
}

export const CRITERION_NAME: Record<string, string> = {
  C1: 'Age 18 or older',
  C2: 'Type 2 diabetes diagnosis',
  C3: 'A1C ≥ 7.0% within 180 days',
  C4: 'Metformin ≥ 90 days, or intolerance',
  C5: 'No MTC or MEN 2',
}
