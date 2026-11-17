import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ViewerField } from './DocumentViewer'
import { EInvoiceView } from './EInvoiceView'

const f = (path: string, section: ViewerField['section'], state: ViewerField['state'] = 'ok'): ViewerField => ({
  path,
  label: path,
  section,
  value: '6627.20',
  confidence: 1,
  source: null,
  locator: 'cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount',
  kind: 'number',
  state,
})

describe('EInvoiceView', () => {
  it('shows XML values with their element and marks failing ones', async () => {
    const onSelect = vi.fn()
    render(
      <EInvoiceView
        fileName="inv.xml"
        fields={[f('number', 'header'), f('total_ttc', 'totals', 'failing')]}
        selected={null}
        onSelect={onSelect}
      />,
    )
    expect(screen.getByText('E-invoice (UBL 2.1)')).toBeInTheDocument()
    const total = screen.getByRole('button', { name: 'total_ttc in the e-invoice' })
    expect(total).toHaveClass('failing')
    expect(total.title).toBe('cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount')
    await userEvent.click(total)
    expect(onSelect).toHaveBeenCalledWith('total_ttc')
  })
})
