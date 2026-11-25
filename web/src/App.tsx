import { useEffect, useMemo, useState } from 'react'
import type { Assessment, CaseSummary, Chart as ChartData, SubmitResult } from './api'
import { api, DECISION_LABEL } from './api'
import { Chart } from './Chart'
import { Review } from './Review'

export default function App() {
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [chart, setChart] = useState<ChartData | null>(null)
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [submitted, setSubmitted] = useState<SubmitResult | null>(null)
  const [highlight, setHighlight] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [passcode, setPasscode] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.cases().then(setCases, (e: Error) => setError(e.message))
  }, [])

  function selectCase(id: string) {
    setSelected(id)
    setChart(null)
    setAssessment(null)
    setSubmitted(null)
    setError(null)
  }

  // Load the chart of the selected case; ignore the answer if the user has
  // moved on to another case by the time it arrives.
  useEffect(() => {
    if (!selected) return
    let current = true
    api.chart(selected).then(
      (c) => current && setChart(c),
      (e: Error) => current && setError(e.message),
    )
    return () => {
      current = false
    }
  }, [selected])

  // Bring a cited record into view when its reference is pointed at.
  useEffect(() => {
    if (!highlight) return
    document
      .querySelector(`[data-ref="${CSS.escape(highlight)}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [highlight])

  const citedBy = useMemo(() => {
    const map = new Map<string, string[]>()
    for (const f of assessment?.findings ?? []) {
      for (const ref of f.evidence) map.set(ref, [...(map.get(ref) ?? []), f.criterion])
    }
    return map
  }, [assessment])

  const summary = cases.find((c) => c.id === selected) ?? null

  async function runAssessment() {
    if (!selected) return
    setRunning(true)
    setError(null)
    setSubmitted(null)
    try {
      setAssessment(await api.assess(selected, live, passcode))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  async function submit() {
    if (!selected) return
    setError(null)
    try {
      setSubmitted(await api.submit(selected))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Prior Auth Copilot</h1>
        <p>
          Checks a semaglutide order against a payer policy using the patient's FHIR chart,
          cites the evidence for every criterion, and submits only after the prescriber signs.
        </p>
        <p className="muted small">
          Synthetic patients and a fictional payer (Example Health Plan). Not for clinical use.
        </p>
      </header>

      <div className="layout">
        <nav className="cases" aria-label="Test cases">
          {(['dev', 'test'] as const).map((split) => (
            <div key={split}>
              <h2>{split === 'dev' ? 'Development cases' : 'Held-out test cases'}</h2>
              <ul>
                {cases
                  .filter((c) => c.split === split)
                  .map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        className={c.id === selected ? 'case active' : 'case'}
                        onClick={() => selectCase(c.id)}
                      >
                        <span className="case-id">{c.id}</span>
                        <span className="case-scenario">{c.scenario}</span>
                        <span className={`expected expected-${c.expected}`}>
                          {DECISION_LABEL[c.expected]}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </nav>

        <main className="main">
          {error && <p className="error">{error}</p>}
          {!selected && <p className="placeholder">Choose a case to see the patient's chart.</p>}
          {selected && !chart && !error && <p className="placeholder">Loading chart…</p>}

          {chart && summary && (
            <div className="workspace">
              <Chart chart={chart} highlight={highlight} citedBy={citedBy} />

              <div className="side">
                <section className="panel run">
                  <h2>Check against policy EHP-RX-0421</h2>
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={live}
                      onChange={(e) => setLive(e.target.checked)}
                    />
                    Live run (calls Claude; needs a passcode)
                  </label>
                  {live && (
                    <input
                      type="password"
                      className="passcode"
                      placeholder="Passcode"
                      value={passcode}
                      onChange={(e) => setPasscode(e.target.value)}
                    />
                  )}
                  <button
                    type="button"
                    className="primary"
                    disabled={running || (live && !passcode)}
                    onClick={runAssessment}
                  >
                    {running ? 'Checking…' : live ? 'Run the agent live' : 'Show saved agent result'}
                  </button>
                  {!live && (
                    <p className="muted small">
                      Shows the agent's recorded output from the evaluation run, at no cost.
                    </p>
                  )}
                </section>

                {assessment && (
                  <Review
                    key={selected} // fresh attestation state for each case
                    summary={summary}
                    assessment={assessment}
                    onPoint={setHighlight}
                    onSubmit={submit}
                    submitted={submitted}
                  />
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
