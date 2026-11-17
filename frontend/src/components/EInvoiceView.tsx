import type { ViewerField } from './DocumentViewer'

type Props = {
  fileName: string
  fields: ViewerField[]
  selected: string | null
  onSelect: (path: string) => void
}

/** An XML e-invoice has no page to look at: show the values as a readable document, each
 * one clickable and marked like a box on a scan, with the XML element it came from. */
export function EInvoiceView({ fileName, fields, selected, onSelect }: Props) {
  const by = (s: ViewerField['section']) => fields.filter((f) => f.section === s)
  const cell = (f: ViewerField | undefined) =>
    f ? (
      <button
        key={f.path}
        className={`xv ${f.state}${f.path === selected ? ' selected' : ''}`}
        title={f.locator ?? undefined}
        aria-label={`${f.label} in the e-invoice`}
        onClick={() => onSelect(f.path)}
      >
        {f.value ?? '—'}
      </button>
    ) : null
  const lines = groupBy(by('lines'))
  const vat = groupBy(by('vat'))
  const cols = lines[0]?.map((f) => f.label) ?? []

  return (
    <div className="einvoice">
      <p className="xhead">
        <b>E-invoice (UBL 2.1)</b> <span className="muted">{fileName}</span>
        <br />
        <span className="muted small">
          Read from the XML, not from an image: hover a value to see its element.
        </span>
      </p>
      {(['header', 'parties'] as const).map((s) => (
        <dl key={s} className="xgrid">
          {by(s).map((f) => (
            <div key={f.path}>
              <dt>{f.label}</dt>
              <dd>{cell(f)}</dd>
            </div>
          ))}
        </dl>
      ))}
      <table className="xtable">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map((row, i) => (
            <tr key={i}>
              {row.map((f) => (
                <td key={f.path}>{cell(f)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {vat.length > 0 && (
        <table className="xtable">
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
                  <td key={f.path}>{cell(f)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <dl className="xgrid">
        {by('totals').map((f) => (
          <div key={f.path}>
            <dt>{f.label}</dt>
            <dd>{cell(f)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function groupBy(items: ViewerField[]): ViewerField[][] {
  const out: ViewerField[][] = []
  for (const it of items) (out[it.line ?? 0] ??= []).push(it)
  return out.filter(Boolean)
}
