import { Link, useSearchParams } from 'react-router'
import type { CaseSummary } from '../api/client'
import { useCases, useMeta, type StatusFilter } from '../api/hooks'

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'open', label: 'To review' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'all', label: 'All' },
]

export function QueuePage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get('status') as StatusFilter | null) ?? 'open'
  const cases = useCases(status)
  const meta = useMeta()

  return (
    <div className="queue">
      <div className="queue-head">
        <h2>Review queue</h2>
        <div className="seg" role="group" aria-label="Status">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              aria-pressed={status === f.value}
              onClick={() => setParams(f.value === 'open' ? {} : { status: f.value })}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {cases.isPending && <p className="page-msg">Loading…</p>}
      {cases.isError && <p className="banner error">{cases.error.message}</p>}
      {cases.data && cases.data.length === 0 && (
        <p className="page-msg">
          {status === 'open' ? 'Nothing to review. Every processed invoice became a draft bill.' : 'No cases.'}
        </p>
      )}
      {cases.data && cases.data.length > 0 && (
        <table className="cases">
          <thead>
            <tr>
              <th>#</th>
              <th>Supplier</th>
              <th>Invoice</th>
              <th>PO</th>
              <th>Why</th>
              <th>Status</th>
              <th>Flagged</th>
            </tr>
          </thead>
          <tbody>
            {cases.data.map((c) => (
              <CaseRow key={c.id} c={c} titles={meta.data?.reasons} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function CaseRow({ c, titles }: { c: CaseSummary; titles?: Record<string, { title: string }> }) {
  return (
    <tr>
      <td className="num">{c.id}</td>
      <td>{c.supplier_name ?? '?'}</td>
      <td>
        <Link to={`/cases/${c.id}`} className="row-link">
          {c.invoice_number ?? '?'}
        </Link>
      </td>
      <td>{c.po_ref ?? '—'}</td>
      <td>
        {c.reason_codes.map((code) => (
          <span key={code} className="chip" title={titles?.[code]?.title}>
            {titles?.[code]?.title ?? code}
          </span>
        ))}
      </td>
      <td>
        <StatusBadge status={c.status} />
      </td>
      <td className="muted">{timeAgo(c.created_at)}</td>
    </tr>
  )
}

export function StatusBadge({ status }: { status: CaseSummary['status'] }) {
  const label = { open: 'to review', approved: 'approved', rejected: 'rejected' }[status]
  return <span className={`badge ${status}`}>{label}</span>
}

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} days ago`
}
