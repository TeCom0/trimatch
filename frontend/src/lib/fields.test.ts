import { describe, expect, it } from 'vitest'
import type { CaseDetail, FailedCheck } from '../api/client'
import caseJson from '../test/fixtures/case-po004.json'
import { checkCovers, fieldState, flattenDoc } from './fields'

const c = caseJson as unknown as CaseDetail

const check = (over: Partial<FailedCheck>): FailedCheck => ({
  code: 'X',
  ok: false,
  detail: '',
  doc: 'invoice',
  line: null,
  title: '',
  hint: '',
  overridable: false,
  fields: [],
  ...over,
})

describe('flattenDoc', () => {
  it('lists every invoice field with the API path, value and box', () => {
    const fields = flattenDoc(c.invoice)
    const byPath = new Map(fields.map((f) => [f.path, f]))
    expect(byPath.get('number')?.value).toBe('FA-DA-2026-0159')
    expect(byPath.get('number')?.source?.page).toBe(1)
    expect(byPath.get('lines.0.unit_price_ht')?.section).toBe('lines')
    expect(byPath.get('vat.0.base_ht')?.kind).toBe('number')
    expect(byPath.get('total_ttc')?.section).toBe('totals')
    // every invoice line gets the 7 line columns
    expect(fields.filter((f) => f.section === 'lines')).toHaveLength(c.invoice.lines.length * 7)
    expect(new Set(fields.map((f) => f.path)).size).toBe(fields.length)
  })

  it('gives a delivery note no prices, VAT or totals', () => {
    const fields = flattenDoc(c.bl!)
    expect(fields.some((f) => f.path.includes('price') || f.section === 'vat')).toBe(false)
    expect(fields.some((f) => f.section === 'totals')).toBe(false)
  })

  it('keeps missing optional fields editable with confidence null', () => {
    const f = flattenDoc(c.invoice).find((x) => x.path === 'customer.name')!
    expect(f.confidence).not.toBeNull()
    const ifNumber = flattenDoc(c.invoice).find((x) => x.path === 'supplier.if_number')!
    expect(ifNumber).toBeDefined()
  })
})

describe('checkCovers', () => {
  it('matches a path or a prefix on a dot boundary', () => {
    const vat = check({ fields: ['vat', 'total_ht'] })
    expect(checkCovers(vat, 'invoice', 'vat.0.base_ht')).toBe(true)
    expect(checkCovers(vat, 'invoice', 'total_ht')).toBe(true)
    expect(checkCovers(vat, 'invoice', 'total_ttc')).toBe(false)
    const line = check({ fields: ['lines.1.quantity'] })
    expect(checkCovers(line, 'invoice', 'lines.1.quantity')).toBe(true)
    expect(checkCovers(line, 'invoice', 'lines.10.quantity')).toBe(false)
  })

  it('respects the document, and order-level checks cover both', () => {
    const bl = check({ doc: 'bl', fields: ['lines.0.quantity'] })
    expect(checkCovers(bl, 'invoice', 'lines.0.quantity')).toBe(false)
    expect(checkCovers(bl, 'bl', 'lines.0.quantity')).toBe(true)
    const po = check({ doc: '', fields: ['po_ref'] })
    expect(checkCovers(po, 'invoice', 'po_ref') && checkCovers(po, 'bl', 'po_ref')).toBe(true)
  })
})

describe('fieldState', () => {
  const f = flattenDoc(c.invoice)[0]
  it('ranks failing > edited > low confidence', () => {
    expect(fieldState(f, true, true)).toBe('failing')
    expect(fieldState(f, false, true)).toBe('edited')
    expect(fieldState({ ...f, confidence: 0.5 }, false, false)).toBe('low')
    expect(fieldState(f, false, false)).toBe('ok')
  })
})
