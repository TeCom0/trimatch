import type { FailedCheck } from '../api/client'

type Props = {
  checks: FailedCheck[]
  checking: boolean
  error: string | null
  onFocus: (check: FailedCheck) => void
}

/** Why the case is here, in words, from the live re-check. */
export function ChecksPanel({ checks, checking, error, onFocus }: Props) {
  return (
    <section className="checks" aria-live="polite" aria-busy={checking}>
      <h3>
        Checks {checking && <span className="spinner" aria-label="checking" />}
      </h3>
      {error && <p className="banner error">{error}</p>}
      {!error && checks.length === 0 && (
        <p className="banner ok">All checks pass. The draft bill can be created.</p>
      )}
      <ul>
        {checks.map((c, i) => (
          <li key={`${c.code}-${c.doc}-${c.line}-${i}`} className={c.overridable ? 'warn' : 'bad'}>
            <button className="check" onClick={() => onFocus(c)} disabled={c.fields.length === 0}>
              <span className="code">{c.code}</span>
              <span className="title">
                {c.title}
                {c.doc && (
                  <span className="where">
                    {' '}
                    · {c.doc === 'bl' ? 'delivery note' : 'invoice'}
                    {c.line !== null && `, line ${c.line + 1}`}
                  </span>
                )}
              </span>
              {c.detail && <span className="detail">{c.detail}</span>}
              {c.hint && <span className="hint">{c.hint}</span>}
              <span className={`tag ${c.overridable ? 'warn' : 'bad'}`}>
                {c.overridable ? 'can be approved with a reason' : 'must be fixed or rejected'}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
