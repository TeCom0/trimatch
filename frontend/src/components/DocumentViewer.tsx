import { useEffect, useRef, useState } from 'react'
import { pageUrl, type DocName } from '../api/client'
import type { FieldEntry, FieldState } from '../lib/fields'

export type ViewerField = FieldEntry & { state: FieldState }

type Props = {
  caseId: number
  doc: DocName
  pages: number
  fields: ViewerField[]
  selected: string | null
  onSelect: (path: string) => void
}

const ZOOMS = [
  { label: 'Fit', value: 0 },
  { label: '100%', value: 1 },
  { label: '150%', value: 1.5 },
  { label: '200%', value: 2 },
]

/** The source page with a box on every extracted value. Boxes are stored normalised
 * (0..1, origin top-left), so they are positioned in percent and follow any zoom. */
export function DocumentViewer({ caseId, doc, pages, fields, selected, onSelect }: Props) {
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(0)
  const [natural, setNatural] = useState<{ w: number } | null>(null)
  const selectedRef = useRef<HTMLButtonElement>(null)

  const selectedField = fields.find((f) => f.path === selected)
  const targetPage = selectedField?.source?.page
  useEffect(() => {
    if (targetPage && targetPage !== page) setPage(targetPage)
  }, [targetPage]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' })
  }, [selected, page])

  const onPage = fields.filter((f) => f.source && f.source.page === page)
  // Natural width / 2: pages are rendered at 144 dpi, so "100%" is print size on screen.
  const width = zoom === 0 || !natural ? '100%' : `${(natural.w / 2) * zoom}px`

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        {pages > 1 && (
          <div className="seg" role="group" aria-label="Page">
            {Array.from({ length: pages }, (_, i) => (
              <button key={i} aria-pressed={page === i + 1} onClick={() => setPage(i + 1)}>
                p. {i + 1}
              </button>
            ))}
          </div>
        )}
        <div className="seg" role="group" aria-label="Zoom">
          {ZOOMS.map((z) => (
            <button key={z.label} aria-pressed={zoom === z.value} onClick={() => setZoom(z.value)}>
              {z.label}
            </button>
          ))}
        </div>
        <span className="legend">
          <i className="sw failing" /> fails a check <i className="sw low" /> low confidence{' '}
          <i className="sw edited" /> corrected
        </span>
      </div>
      <div className="viewer-scroll">
        <div className="page" style={{ width }}>
          <img
            src={pageUrl(caseId, doc, page)}
            alt={`${doc === 'invoice' ? 'Invoice' : 'Delivery note'}, page ${page}`}
            onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth })}
            draggable={false}
          />
          {onPage.map((f) => {
            const b = f.source!
            const isSel = f.path === selected
            return (
              <button
                key={f.path}
                ref={isSel ? selectedRef : undefined}
                className={`box ${f.state}${isSel ? ' selected' : ''}`}
                style={{
                  left: `${b.x0 * 100}%`,
                  top: `${b.y0 * 100}%`,
                  width: `${(b.x1 - b.x0) * 100}%`,
                  height: `${(b.y1 - b.y0) * 100}%`,
                }}
                title={`${f.label}: ${f.value ?? '—'}`}
                aria-label={`${f.label} on the document`}
                onClick={() => onSelect(f.path)}
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}
