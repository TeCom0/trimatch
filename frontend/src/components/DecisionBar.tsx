import { useState } from 'react'
import type { RecheckOut } from '../api/client'

type Props = {
  recheck: RecheckOut | undefined
  pending: boolean // edits not re-checked yet, or a decision in flight
  corrections: number
  minReason: number
  error: string | null
  onApprove: (reason: string | null) => void
  onReject: (reason: string) => void
}

/** Approve (draft bill) or reject, with the rules of plan D2 spelled out on the button. */
export function DecisionBar(props: Props) {
  const { recheck, pending, corrections, minReason, error, onApprove, onReject } = props
  const [reason, setReason] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const trimmed = reason.trim()
  const reasonOk = trimmed.length >= minReason

  const needsReason = !!recheck?.needs_reason
  const approveBlocked =
    !recheck || pending || !recheck.can_approve || (needsReason && !reasonOk)
  let approveNote = ''
  if (!recheck) approveNote = 'Checking…'
  else if (recheck.already_drafted)
    approveNote = `Odoo already has bill ${recheck.already_drafted.name ?? `#${recheck.already_drafted.id}`} for this invoice.`
  else if (recheck.blocking.length)
    approveNote = `Fix or reject: ${recheck.blocking.join(', ')} cannot be overridden.`
  else if (needsReason && !reasonOk)
    approveNote = `Approving over ${recheck.overridable.join(', ')} needs a reason (${minReason}+ characters).`
  else if (pending) approveNote = 'Re-checking your corrections…'

  const showReason = needsReason || rejecting
  return (
    <section className="decision">
      {showReason && (
        <label className="reason">
          <span>
            {rejecting ? 'Why reject?' : `Why approve over ${recheck?.overridable.join(', ')}?`}
          </span>
          <textarea
            value={reason}
            rows={2}
            placeholder={
              rejecting
                ? 'e.g. Short delivery: credit note requested from the supplier.'
                : 'e.g. New price agreed with the supplier on 9 Nov.'
            }
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      )}
      {error && <p className="banner error">{error}</p>}
      <div className="buttons">
        {!rejecting ? (
          <>
            <button
              className="primary"
              disabled={approveBlocked}
              onClick={() => onApprove(needsReason ? trimmed : null)}
            >
              Approve → draft bill in Odoo
              {corrections > 0 && <small> ({corrections} correction{corrections > 1 ? 's' : ''})</small>}
            </button>
            <button className="ghost" onClick={() => setRejecting(true)}>
              Reject…
            </button>
          </>
        ) : (
          <>
            <button className="danger" disabled={!reasonOk || pending} onClick={() => onReject(trimmed)}>
              Reject case
            </button>
            <button className="ghost" onClick={() => setRejecting(false)}>
              Cancel
            </button>
          </>
        )}
      </div>
      {!rejecting && approveNote && <p className="note">{approveNote}</p>}
      <p className="note muted">Nothing is posted or paid: approval only creates a draft.</p>
    </section>
  )
}
