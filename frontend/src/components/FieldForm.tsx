import type { DocName, FailedCheck, PoOut } from '../api/client'
import { checksFor, type FieldEntry, type FieldState } from '../lib/fields'

export type FormField = FieldEntry & { state: FieldState; edited: string | null | undefined }

type Props = {
  doc: DocName
  fields: FormField[]
  checks: FailedCheck[]
  po: PoOut | null | undefined
  readOnly: boolean
  selected: string | null
  onSelect: (path: string) => void
  onChange: (f: FormField, value: string | null) => void
  onReset: (f: FormField) => void
}

function FieldInput({
  f,
  readOnly,
  selected,
  problems,
  onSelect,
  onChange,
  onReset,
  compact,
}: {
  f: FormField
  readOnly: boolean
  selected: boolean
  problems: FailedCheck[]
  onSelect: () => void
  onChange: (v: string | null) => void
  onReset: () => void
  compact?: boolean
}) {
  const value = f.edited !== undefined ? f.edited : f.value
  const id = `f-${f.path}`
  return (
    <div className={`field ${f.state}${selected ? ' selected' : ''}${compact ? ' compact' : ''}`}>
      {!compact && (
        <label htmlFor={id}>
          {f.label}
          {f.confidence !== null && f.confidence < 1 && f.edited === undefined && (
            <span className="conf" title="Extractor's self-reported confidence">
              {Math.round(f.confidence * 100)}%
            </span>
          )}
        </label>
      )}
      <div className="field-row">
        <input
          id={id}
          value={value ?? ''}
          placeholder="—"
          readOnly={readOnly}
          inputMode={f.kind === 'number' ? 'decimal' : undefined}
          aria-label={compact ? f.label : undefined}
          aria-invalid={f.state === 'failing' || undefined}
          title={problems.map((p) => p.title).join(', ') || undefined}
          onFocus={onSelect}
          onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        />
        {f.edited !== undefined && !readOnly && (
          <button className="reset" title={`Read as: ${f.value ?? '—'}. Undo`} onClick={onReset}>
            ↺
          </button>
        )}
      </div>
      {f.edited !== undefined && !compact && (
        <div className="was">read as {f.value ?? '—'}</div>
      )}
    </div>
  )
}

const SECTION_TITLES = { header: 'Document', parties: 'Parties', totals: 'Totals' } as const

export function FieldForm(props: Props) {
  const { doc, fields, checks, po, readOnly, selected, onSelect, onChange, onReset } = props
  const input = (f: FormField, compact = false) => (
    <FieldInput
      key={f.path}
      f={f}
      compact={compact}
      readOnly={readOnly}
      selected={selected === f.path}
      problems={checksFor(checks, doc, f.path)}
      onSelect={() => onSelect(f.path)}
      onChange={(v) => onChange(f, v)}
      onReset={() => onReset(f)}
    />
  )
  const bySection = (s: FieldEntry['section']) => fields.filter((f) => f.section === s)
  const lines = groupBy(bySection('lines'), (f) => f.line!)
  const vat = groupBy(bySection('vat'), (f) => f.line!)
  // Lines are paired to PO lines by supplier ref = product code (match.pair_lines).
  const poByCode = new Map((po?.lines ?? []).map((l) => [l.default_code, l]))

  return (
    <div className="form">
      {(['header', 'parties'] as const).map((s) => (
        <section key={s}>
          <h3>{SECTION_TITLES[s]}</h3>
          <div className="grid">{bySection(s).map((f) => input(f))}</div>
        </section>
      ))}

      <section>
        <h3>Lines</h3>
        <ol className="line-cards">
          {lines.map((row, i) => {
            const ref = row.find((f) => f.path.endsWith('.supplier_ref'))
            const pl = poByCode.get(String(ref?.edited ?? ref?.value ?? ''))
            const desc = row.find((f) => f.path.endsWith('.description'))
            const rest = row.filter((f) => f !== desc)
            return (
              <li key={i} className="line-card">
                <span className="num">{i + 1}</span>
                <div className="line-body">
                  {desc && <div className="line-desc">{input(desc, true)}</div>}
                  <div className="line-grid" style={{ gridTemplateColumns: `repeat(${rest.length}, minmax(0, 1fr))` }}>
                    {rest.map((f) => (
                      <div key={f.path}>
                        <span className="mini">{f.label}</span>
                        {input(f, true)}
                      </div>
                    ))}
                  </div>
                  {po && (
                    <div className="po">
                      {pl ? (
                        <>
                          {po.name}: ordered {fmt(pl.qty_ordered)} · received{' '}
                          <b>{fmt(pl.qty_received)}</b>
                          {Number(pl.qty_invoiced) > 0 && <> · billed {fmt(pl.qty_invoiced)}</>} ·
                          price <b>{fmt(pl.price_unit)}</b> / {pl.uom}
                        </>
                      ) : (
                        <span>not on {po.name}</span>
                      )}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </section>

      {vat.length > 0 && (
        <section>
          <h3>VAT</h3>
          <table className="lines vat">
            <thead>
              <tr>
                {vat[0].map((f) => (
                  <th key={f.label}>{f.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {vat.map((row, i) => (
                <tr key={i}>
                  {row.map((f) => (
                    <td key={f.path}>{input(f, true)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {bySection('totals').length > 0 && (
        <section>
          <h3>{SECTION_TITLES.totals}</h3>
          <div className="grid">{bySection('totals').map((f) => input(f))}</div>
        </section>
      )}
    </div>
  )
}

function groupBy<T>(items: T[], key: (t: T) => number): T[][] {
  const out: T[][] = []
  for (const it of items) (out[key(it)] ??= []).push(it)
  return out.filter(Boolean)
}

function fmt(v: string | number): string {
  const n = Number(v)
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}
