// Turns an extracted document (schema.Invoice / schema.DeliveryNote as JSON) into the flat
// list of editable fields the form and the document viewer share. A field's `path` is the
// same dotted path the API takes in an edit ("lines.2.unit_price_ht").
import type { Box, DocName, FailedCheck, Schemas } from '../api/client'

export type Invoice = Schemas['Invoice']
export type DeliveryNote = Schemas['DeliveryNote']
export type Doc = Invoice | DeliveryNote

type ExtractedField = { value: string | null; confidence: number; source?: Box | null }

export type Section = 'header' | 'parties' | 'lines' | 'vat' | 'totals'

export type FieldEntry = {
  path: string
  label: string
  section: Section
  value: string | null
  confidence: number | null // null: the extractor returned nothing for this field
  source: Box | null
  kind: 'text' | 'number' | 'date'
  line?: number
}

const isInvoice = (d: Doc): d is Invoice => d.doc_type === 'invoice'

function entry(
  path: string,
  label: string,
  section: Section,
  f: ExtractedField | null | undefined,
  kind: FieldEntry['kind'] = 'text',
  line?: number,
): FieldEntry {
  return {
    path,
    label,
    section,
    value: f?.value ?? null,
    confidence: f ? f.confidence : null,
    source: f?.source ?? null,
    kind,
    line,
  }
}

export function flattenDoc(doc: Doc): FieldEntry[] {
  const out: FieldEntry[] = [
    entry('number', 'Number', 'header', doc.number),
    entry('date', 'Date', 'header', doc.date, 'date'),
  ]
  if (isInvoice(doc)) {
    out.push(entry('due_date', 'Due date', 'header', doc.due_date, 'date'))
  }
  out.push(entry('po_ref', 'PO reference', 'header', doc.po_ref))
  if (isInvoice(doc)) {
    doc.bl_refs.forEach((r, i) => out.push(entry(`bl_refs.${i}`, 'Delivery note', 'header', r)))
    out.push(entry('payment_terms', 'Payment terms', 'header', doc.payment_terms))
  }
  for (const [party, title] of [
    ['supplier', 'Supplier'],
    ['customer', 'Customer'],
  ] as const) {
    const p = doc[party]
    out.push(entry(`${party}.name`, `${title} name`, 'parties', p.name))
    out.push(entry(`${party}.ice`, `${title} ICE`, 'parties', p.ice))
    if (party === 'supplier') {
      out.push(entry(`${party}.if_number`, `${title} IF`, 'parties', p.if_number))
      out.push(entry(`${party}.tp_number`, `${title} TP`, 'parties', p.tp_number))
      out.push(entry(`${party}.rc`, `${title} RC`, 'parties', p.rc))
    }
  }
  doc.lines.forEach((ln, i) => {
    const p = `lines.${i}`
    out.push(entry(`${p}.description`, 'Description', 'lines', ln.description, 'text', i))
    out.push(entry(`${p}.supplier_ref`, 'Ref', 'lines', ln.supplier_ref, 'text', i))
    out.push(entry(`${p}.quantity`, 'Qty', 'lines', ln.quantity, 'number', i))
    out.push(entry(`${p}.unit`, 'Unit', 'lines', ln.unit, 'text', i))
    if (isInvoice(doc)) {
      out.push(entry(`${p}.unit_price_ht`, 'Unit price HT', 'lines', ln.unit_price_ht, 'number', i))
      out.push(entry(`${p}.vat_rate`, 'VAT %', 'lines', ln.vat_rate, 'number', i))
      out.push(entry(`${p}.line_total_ht`, 'Total HT', 'lines', ln.line_total_ht, 'number', i))
    }
  })
  if (isInvoice(doc)) {
    doc.vat.forEach((v, i) => {
      out.push(entry(`vat.${i}.rate`, 'Rate %', 'vat', v.rate, 'number', i))
      out.push(entry(`vat.${i}.base_ht`, 'Base HT', 'vat', v.base_ht, 'number', i))
      out.push(entry(`vat.${i}.amount`, 'VAT', 'vat', v.amount, 'number', i))
    })
    out.push(entry('total_ht', 'Total HT', 'totals', doc.total_ht, 'number'))
    out.push(entry('total_ttc', 'Total TTC', 'totals', doc.total_ttc, 'number'))
  }
  return out
}

export const fieldKey = (doc: DocName, path: string) => `${doc}:${path}`

/** Does a check point at this field? Check field patterns are prefixes on a path
 * boundary: "vat" covers "vat.0.base_ht"; "lines.2.quantity" covers only itself. */
export function checkCovers(check: FailedCheck, doc: DocName, path: string): boolean {
  if (check.doc && check.doc !== doc) return false
  return check.fields.some((f) => path === f || path.startsWith(`${f}.`))
}

export function checksFor(checks: FailedCheck[], doc: DocName, path: string): FailedCheck[] {
  return checks.filter((c) => checkCovers(c, doc, path))
}

export const LOW_CONFIDENCE = 0.85 // config/matching.yaml min_field_confidence

export type FieldState = 'failing' | 'edited' | 'low' | 'ok'

export function fieldState(
  f: FieldEntry,
  failing: boolean,
  edited: boolean,
): FieldState {
  if (failing) return 'failing'
  if (edited) return 'edited'
  if (f.confidence !== null && f.confidence < LOW_CONFIDENCE) return 'low'
  return 'ok'
}
