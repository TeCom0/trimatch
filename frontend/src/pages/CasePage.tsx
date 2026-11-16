import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import type { ApproveOut, CaseDetail, DocName, FailedCheck } from '../api/client'
import { ApiError } from '../api/client'
import { useApprove, useCase, useMeta, useRecheck, useReject } from '../api/hooks'
import { ChecksPanel } from '../components/ChecksPanel'
import { DecisionBar } from '../components/DecisionBar'
import { DocumentViewer } from '../components/DocumentViewer'
import { FieldForm, type FormField } from '../components/FieldForm'
import { checkCovers, fieldState, flattenDoc } from '../lib/fields'
import { useEdits } from '../lib/useEdits'
import { StatusBadge, timeAgo } from './QueuePage'

const DOC_LABEL: Record<DocName, string> = { invoice: 'Invoice', bl: 'Delivery note' }

export function CasePage() {
  const id = Number(useParams().id)
  const caseQ = useCase(id)
  if (caseQ.isPending) return <p className="page-msg">Loading case #{id}…</p>
  if (caseQ.isError) return <p className="page-msg banner error">{caseQ.error.message}</p>
  return <CaseView key={id} c={caseQ.data} />
}

function CaseView({ c }: { c: CaseDetail }) {
  const meta = useMeta()
  const open = c.status === 'open'
  const edits = useEdits()
  const recheck = useRecheck(c.id, edits.debounced, open)
  const approve = useApprove(c.id)
  const reject = useReject(c.id)
  const [doc, setDoc] = useState<DocName>('invoice')
  const [selected, setSelected] = useState<string | null>(null)
  const [approved, setApproved] = useState<ApproveOut | null>(null)

  const checks: FailedCheck[] = open ? (recheck.data?.failed ?? c.reasons) : c.reasons
  const docJson = doc === 'invoice' ? c.invoice : c.bl
  const fields: FormField[] = useMemo(() => {
    if (!docJson) return []
    return flattenDoc(docJson).map((f) => {
      const edit = edits.get(doc, f.path)
      const failing = checks.some((ch) => checkCovers(ch, doc, f.path))
      return {
        ...f,
        edited: edit === undefined ? undefined : edit.value,
        state: fieldState(f, failing, edit !== undefined),
      }
    })
  }, [docJson, doc, edits, checks])

  const focusCheck = (ch: FailedCheck) => {
    const target: DocName = ch.doc === 'bl' && c.bl ? 'bl' : ch.doc === 'invoice' ? 'invoice' : doc
    const json = target === 'invoice' ? c.invoice : c.bl
    const first = json && flattenDoc(json).find((f) => checkCovers(ch, target, f.path))
    setDoc(target)
    if (first) {
      setSelected(first.path)
      requestAnimationFrame(() => document.getElementById(`f-${first.path}`)?.focus())
    }
  }

  const mutationError = approve.error ?? reject.error
  const errorText =
    mutationError instanceof ApiError || mutationError instanceof Error ? mutationError.message : null
  const recheckError = recheck.error ? recheck.error.message : null
  const lastAction = c.actions.at(-1)
  const odooUrl = meta.data?.odoo_url
  const billId = approved?.bill.id ?? lastAction?.odoo_bill_id

  return (
    <div className="case">
      <header className="case-head">
        <Link to="/" className="back">
          ← Queue
        </Link>
        <h2>
          {c.invoice_number ?? 'Invoice ?'} <span className="muted">· {c.supplier_name}</span>{' '}
          <span className="muted">· {c.po_ref ?? 'no PO'}</span>
        </h2>
        <StatusBadge status={c.status} />
        <span className="muted small">flagged {timeAgo(c.created_at)}</span>
      </header>

      <div className="split">
        <div className="left">
          <div className="tabs" role="tablist">
            {(['invoice', 'bl'] as const).map((d) => (
              <button
                key={d}
                role="tab"
                aria-selected={doc === d}
                disabled={!c.documents[d]}
                onClick={() => {
                  setDoc(d)
                  setSelected(null)
                }}
              >
                {DOC_LABEL[d]}
                <small>{c.documents[d]?.file_name ?? 'missing'}</small>
              </button>
            ))}
          </div>
          {c.documents[doc] ? (
            <DocumentViewer
              key={doc}
              caseId={c.id}
              doc={doc}
              pages={c.documents[doc].pages}
              fields={fields}
              selected={selected}
              onSelect={(p) => {
                setSelected(p)
                document.getElementById(`f-${p}`)?.focus()
              }}
            />
          ) : (
            <p className="page-msg">The {DOC_LABEL[doc].toLowerCase()} file is not on disk.</p>
          )}
        </div>

        <div className="right">
          {open && !approved ? (
            <>
              <ChecksPanel
                checks={checks}
                checking={recheck.isFetching || edits.pending}
                error={recheckError}
                onFocus={focusCheck}
              />
              <DecisionBar
                recheck={recheck.data}
                pending={edits.pending || recheck.isFetching || approve.isPending || reject.isPending}
                corrections={edits.count}
                minReason={meta.data?.min_reason_chars ?? 10}
                error={errorText}
                onApprove={(reason) =>
                  approve.mutate({ edits: edits.list, reason }, { onSuccess: setApproved })
                }
                onReject={(reason) => reject.mutate({ edits: edits.list, reason })}
              />
            </>
          ) : (
            <section className="outcome">
              {approved || c.status === 'approved' ? (
                <p className="banner ok">
                  Approved{lastAction ? ` by ${lastAction.reviewer}` : ''}. Draft bill created in
                  Odoo
                  {billId && odooUrl && (
                    <>
                      {': '}
                      <a href={`${odooUrl}/odoo/account.move/${billId}`} target="_blank" rel="noreferrer">
                        open bill #{billId}
                      </a>
                    </>
                  )}
                  .{approved?.note_error && ` (The note on the bill failed: ${approved.note_error})`}
                </p>
              ) : (
                <p className="banner error">
                  Rejected by {lastAction?.reviewer}: {lastAction?.reason}
                </p>
              )}
              {lastAction?.reason && c.status === 'approved' && (
                <p className="muted">
                  Reason: {lastAction.reason}
                  {lastAction.overridden_codes.length > 0 &&
                    ` (overrode ${lastAction.overridden_codes.join(', ')})`}
                </p>
              )}
              {c.corrections.length > 0 && (
                <>
                  <h3>Corrections</h3>
                  <ul className="corrections">
                    {c.corrections.map((k, i) => (
                      <li key={i}>
                        {k.doc} <code>{k.field_path}</code>: {String(k.old_value ?? '—')} →{' '}
                        <b>{String(k.new_value ?? '—')}</b>{' '}
                        {k.old_confidence !== null && (
                          <span className="muted">(read at {Math.round(k.old_confidence * 100)}%)</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <Link to="/" className="button">
                Back to the queue
              </Link>
            </section>
          )}

          <h3 className="form-title">{DOC_LABEL[doc]} as read</h3>
          <FieldForm
            doc={doc}
            fields={fields}
            checks={checks}
            po={recheck.data?.po ?? c.odoo_po}
            readOnly={!open || !!approved}
            selected={selected}
            onSelect={setSelected}
            onChange={(f, v) => edits.set(doc, f.path, v, f.value)}
            onReset={(f) => edits.reset(doc, f.path)}
          />
        </div>
      </div>
    </div>
  )
}
