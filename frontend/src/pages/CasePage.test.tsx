// The review flow against a stubbed API, using responses recorded from the real API
// (case PO-004: price +8% over the PO, PRICE_OVER_TOLERANCE).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import caseJson from '../test/fixtures/case-po004.json'
import metaJson from '../test/fixtures/meta.json'
import recheckJson from '../test/fixtures/recheck-po004.json'
import { CasePage } from './CasePage'

type Call = { method: string; path: string; body: unknown }
let calls: Call[]
let approveStatus: number

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  calls = []
  approveStatus = 200
  vi.stubGlobal('fetch', async (req: Request) => {
    const url = new URL(req.url, 'http://test')
    const body = req.method === 'POST' ? await req.json() : undefined
    calls.push({ method: req.method, path: url.pathname, body })
    if (url.pathname === '/api/meta') return json(metaJson)
    if (url.pathname === '/api/reviews/2') return json(caseJson)
    if (url.pathname === '/api/reviews/2/recheck') return json(recheckJson)
    if (url.pathname === '/api/reviews/2/approve') {
      if (approveStatus !== 200) return json({ detail: 'Odoo: down', checks: [] }, approveStatus)
      return json({
        case: { ...caseJson, status: 'approved' },
        bill: { id: 42, name: null, state: 'draft', amount_total: 5040.48 },
        corrections: 0,
        overridden: ['PRICE_OVER_TOLERANCE'],
        note_error: null,
      })
    }
    return json({ detail: `unexpected ${url.pathname}` }, 404)
  })
})

afterEach(() => vi.unstubAllGlobals())

function renderCase() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/cases/2']}>
        <Routes>
          <Route path="/cases/:id" element={<CasePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CasePage', () => {
  it('shows why the case is here and highlights the field on the page', async () => {
    renderCase()
    expect(await screen.findByText('Price differs from the PO')).toBeInTheDocument()
    expect(screen.getByText(/ANF-HT05: invoiced 99.36, PO price 92/)).toBeInTheDocument()
    expect(screen.getByText('can be approved with a reason')).toBeInTheDocument()
    // the failing price has a red box on the document and a red input in the form
    const failingBoxes = document.querySelectorAll('.box.failing')
    expect(failingBoxes.length).toBe(1)
    expect(document.querySelector('.field.failing input')).toHaveValue('99.36')
    // PO comparison next to the line
    expect(screen.getAllByText(/received/).length).toBeGreaterThan(0)
  })

  it('needs a reason before approving over the price, then creates the draft', async () => {
    const user = userEvent.setup()
    renderCase()
    const approve = await screen.findByRole('button', { name: /Approve → draft bill/ })
    await waitFor(() => expect(screen.getByText(/needs a reason/)).toBeInTheDocument())
    expect(approve).toBeDisabled()

    await user.type(screen.getByRole('textbox', { name: /Why approve over/ }), 'Agreed new price on 9 Nov.')
    await waitFor(() => expect(approve).toBeEnabled())
    await user.click(approve)

    expect(await screen.findByText(/Draft bill created in Odoo/)).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/api/reviews/2/approve')!
    expect(post.body).toEqual({ edits: [], reason: 'Agreed new price on 9 Nov.' })
    expect(screen.getByRole('link', { name: 'open bill #42' })).toHaveAttribute(
      'href',
      `${metaJson.odoo_url}/odoo/account.move/42`,
    )
  })

  it('sends a correction to the re-check and with the approval', async () => {
    const user = userEvent.setup()
    renderCase()
    await screen.findByText('Price differs from the PO')
    const price = document.querySelector<HTMLInputElement>('.field.failing input')!
    expect(price).toHaveAccessibleName('Unit price HT')
    await user.clear(price)
    await user.type(price, '92.00')
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path === '/api/reviews/2/recheck' &&
            JSON.stringify(c.body).includes('"value":"92.00"'),
        ),
      ).toBe(true),
    )
    const edit = (calls.at(-1)!.body as { edits: { path: string }[] }).edits[0]
    expect(edit.path).toMatch(/^lines\.\d\.unit_price_ht$/)
    // the field is marked corrected and can be undone
    expect(screen.getByTitle('Read as: 99.36. Undo')).toBeInTheDocument()
  })

  it('shows the server error when Odoo refuses', async () => {
    approveStatus = 502
    const user = userEvent.setup()
    renderCase()
    await user.type(await screen.findByRole('textbox', { name: /Why approve over/ }), 'Agreed new price on 9 Nov.')
    const approve = screen.getByRole('button', { name: /Approve → draft bill/ })
    await waitFor(() => expect(approve).toBeEnabled())
    await user.click(approve)
    expect(await screen.findByText('Odoo: down')).toBeInTheDocument()
    expect(within(document.querySelector('.case-head')!).getByText('to review')).toBeInTheDocument()
  })
})
