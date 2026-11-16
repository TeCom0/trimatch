import { Link, Route, Routes } from 'react-router'
import { useMeta } from './api/hooks'
import { CasePage } from './pages/CasePage'
import { QueuePage } from './pages/QueuePage'

export default function App() {
  const meta = useMeta()
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          trimatch <span>review</span>
        </Link>
        <span className="spacer" />
        {meta.data && (
          <>
            <a href={meta.data.odoo_url} target="_blank" rel="noreferrer" className="muted">
              Odoo ↗
            </a>
            <span className={`reviewer${meta.data.reviewer ? '' : ' missing'}`}>
              {meta.data.reviewer ?? 'TRIMATCH_REVIEWER not set'}
            </span>
          </>
        )}
      </header>
      <main>
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/cases/:id" element={<CasePage />} />
          <Route path="*" element={<p className="page-msg">Not found.</p>} />
        </Routes>
      </main>
    </div>
  )
}
