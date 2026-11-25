import type { ReactNode } from 'react'
import type { Chart as ChartData } from './api'

interface Props {
  chart: ChartData
  highlight: string | null // the FHIR reference being pointed at, if any
  citedBy: Map<string, string[]> // FHIR reference -> criteria that cite it
}

interface RecordProps {
  fhirRef: string
  highlight: string | null
  citedBy: Map<string, string[]>
  children: ReactNode
}

// One chart entry, tagged with its FHIR reference and the criteria citing it.
function Record({ fhirRef, highlight, citedBy, children }: RecordProps) {
  const criteria = citedBy.get(fhirRef) ?? []
  return (
    <li data-ref={fhirRef} className={fhirRef === highlight ? 'record highlight' : 'record'}>
      <div className="record-body">{children}</div>
      <div className="record-meta">
        <code>{fhirRef}</code>
        {criteria.map((c) => (
          <span key={c} className="cited-tag" title={`Cited for ${c}`}>
            {c}
          </span>
        ))}
      </div>
    </li>
  )
}

// The patient's chart, as the agent's tools return it. Every record carries
// its FHIR reference, so a cited reference can be found and highlighted here.
export function Chart({ chart, highlight, citedBy }: Props) {
  const { patient, conditions, observations, medications, notes } = chart
  const shared = { highlight, citedBy }

  return (
    <section className="panel chart">
      <h2>Chart</h2>
      <ul className="records">
        <Record fhirRef={patient.ref} {...shared}>
          <strong>{patient.name}</strong>, {patient.gender}, born {patient.birth_date}
        </Record>
      </ul>

      <h3>Diagnoses</h3>
      <ul className="records">
        {conditions.map((c) => (
          <Record key={c.ref} fhirRef={c.ref} {...shared}>
            <span className="code">{c.code}</span> {c.display}
            <span className="muted">
              {' '}
              · {c.clinical_status}, since {c.onset}
            </span>
          </Record>
        ))}
      </ul>

      <h3>Labs and vitals</h3>
      <ul className="records">
        {observations.length === 0 && <li className="muted">No results on file</li>}
        {observations.map((o) => (
          <Record key={o.ref} fhirRef={o.ref} {...shared}>
            <span className="muted">{o.date}</span> {o.display}:{' '}
            <strong>
              {o.value} {o.unit}
            </strong>
          </Record>
        ))}
      </ul>

      <h3>Medications</h3>
      <ul className="records">
        {medications.map((m) => (
          <Record key={m.ref} fhirRef={m.ref} {...shared}>
            {m.display} <span className={`badge med-${m.status}`}>{m.status}</span>
            <span className="muted"> · written {m.authored_on}</span>
            {m.status === 'draft' && <div className="muted">Awaiting prior authorization</div>}
          </Record>
        ))}
      </ul>

      <h3>Clinical notes</h3>
      <ul className="records">
        {notes.length === 0 && <li className="muted">No notes</li>}
        {notes.map((n) => (
          <Record key={n.ref} fhirRef={n.ref} {...shared}>
            <div className="muted">{n.date}</div>
            <p className="note">{n.text}</p>
          </Record>
        ))}
      </ul>
    </section>
  )
}
