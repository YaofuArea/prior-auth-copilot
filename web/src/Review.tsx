import { useState } from 'react'
import type { Assessment, CaseSummary, SubmitResult } from './api'
import { CRITERION_NAME, DECISION_LABEL, STATUS_LABEL } from './api'

interface Props {
  summary: CaseSummary
  assessment: Assessment
  onPoint: (fhirRef: string | null) => void // highlight a cited record in the chart
  onSubmit: () => Promise<void>
  submitted: SubmitResult | null
}

export function Review({ summary, assessment, onPoint, onSubmit, submitted }: Props) {
  const { decision, findings } = assessment
  const matches = decision === summary.expected

  return (
    <section className="panel review">
      <div className={`decision decision-${decision}`}>
        <div className="decision-label">{DECISION_LABEL[decision]}</div>
        <div className="decision-meta">
          Expected for this test case: {DECISION_LABEL[summary.expected]}{' '}
          {matches ? '✓' : '✗'}
        </div>
      </div>
      <p className="muted small">
        {assessment.model}, {assessment.source}. Hover a cited record to find it in the chart.
      </p>

      {assessment.cited_but_unseen.length > 0 && (
        <p className="warning">
          The agent cited records its tools never returned:{' '}
          {assessment.cited_but_unseen.join(', ')}
        </p>
      )}

      <ol className="findings">
        {findings.map((f) => (
          <li key={f.criterion} className="finding">
            <div className="finding-head">
              <span className="criterion">{f.criterion}</span>
              <span className="criterion-name">{CRITERION_NAME[f.criterion]}</span>
              <span className={`status status-${f.status}`}>{STATUS_LABEL[f.status]}</span>
            </div>
            <p className="reason">{f.reason}</p>
            <div className="evidence">
              {f.evidence.map((ref) => (
                <button
                  key={ref}
                  type="button"
                  className="evidence-ref"
                  onMouseEnter={() => onPoint(ref)}
                  onMouseLeave={() => onPoint(null)}
                  onFocus={() => onPoint(ref)}
                  onBlur={() => onPoint(null)}
                >
                  {ref}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ol>

      {decision === 'meets' && (
        <SignAndSubmit assessment={assessment} onSubmit={onSubmit} submitted={submitted} />
      )}
      {decision === 'missing' && (
        <div className="outcome">
          <h3>Before submitting, add to the chart</h3>
          <ul>
            {assessment.todo?.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {decision === 'not_met' && (
        <div className="outcome">
          <h3>Not submittable: the request would not be approved</h3>
          <ul>
            {assessment.reasons?.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

interface SignProps {
  assessment: Assessment
  onSubmit: () => Promise<void>
  submitted: SubmitResult | null
}

function SignAndSubmit({ assessment, onSubmit, submitted }: SignProps) {
  const [attested, setAttested] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function submit() {
    setSubmitting(true)
    try {
      await onSubmit()
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    const { claim } = submitted
    return (
      <div className="outcome submitted">
        <h3>Submitted</h3>
        <p>
          Stored on the FHIR server as <code>Claim/{claim.id}</code> (use:{' '}
          <code>{claim.use}</code>) with <code>{submitted.letter_ref}</code>.
        </p>
        <h4>Supporting information sent with the request</h4>
        <ul className="supporting">
          {claim.supportingInfo.map((s) => (
            <li key={s.sequence}>
              <span className="muted">{s.category.text}</span>{' '}
              <code>{s.valueReference.reference}</code>
            </li>
          ))}
        </ul>
        <details>
          <summary>FHIR Claim as stored</summary>
          <pre className="json">{JSON.stringify(claim, null, 2)}</pre>
        </details>
      </div>
    )
  }

  return (
    <div className="outcome">
      <h3>Draft letter of medical necessity</h3>
      <pre className="letter">{assessment.letter}</pre>
      <p className="muted small">
        Assembled from the findings above, not written by a second model call.
        Nothing is sent until the prescriber signs.
      </p>
      <label className="attest">
        <input
          type="checkbox"
          checked={attested}
          onChange={(e) => setAttested(e.target.checked)}
        />
        <span>
          <strong>Prescriber attestation (C5):</strong> {assessment.attestation}
        </span>
      </label>
      <button
        type="button"
        className="primary"
        disabled={!attested || submitting}
        onClick={submit}
      >
        {submitting ? 'Submitting…' : 'Sign and submit'}
      </button>
    </div>
  )
}
