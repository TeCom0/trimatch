import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DocumentViewer, type ViewerField } from './DocumentViewer'

const field = (path: string, approximate: boolean, state: ViewerField['state'] = 'ok'): ViewerField => ({
  path,
  label: path,
  section: 'totals',
  value: '1.00',
  confidence: 1,
  kind: 'number',
  state,
  source: { page: 1, x0: 0.5, y0: 0.25, x1: 0.75, y1: 0.3, approximate },
})

describe('DocumentViewer', () => {
  it('places boxes in page percent, dashes approximate ones and reports clicks', async () => {
    const onSelect = vi.fn()
    render(
      <DocumentViewer
        caseId={1}
        doc="invoice"
        pages={1}
        fields={[field('total_ht', false, 'failing'), field('total_ttc', true)]}
        selected="total_ht"
        onSelect={onSelect}
      />,
    )
    const exact = screen.getByRole('button', { name: 'total_ht on the document' })
    const approx = screen.getByRole('button', { name: 'total_ttc on the document' })
    expect(exact).toHaveClass('box', 'failing', 'selected')
    expect(exact).not.toHaveClass('approx')
    expect(approx).toHaveClass('approx')
    expect(approx.title).toMatch(/approximate position/)
    expect(exact.style.left).toBe('50%')
    expect(exact.style.top).toBe('25%')
    expect(exact.style.width).toBe('25%')
    await userEvent.click(approx)
    expect(onSelect).toHaveBeenCalledWith('total_ttc')
  })
})
