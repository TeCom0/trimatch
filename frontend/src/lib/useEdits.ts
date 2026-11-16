import { useCallback, useEffect, useMemo, useState } from 'react'
import type { DocName, EditIn } from '../api/client'
import { fieldKey } from './fields'

/** The reviewer's corrections, keyed by document + path. `debounced` is what goes to the
 * re-check, so it isn't called on every keystroke. */
export function useEdits(delayMs = 350) {
  const [edits, setEdits] = useState<Map<string, EditIn>>(new Map())
  const list = useMemo(
    () => [...edits.values()].sort((a, b) => fieldKey(a.doc, a.path).localeCompare(fieldKey(b.doc, b.path))),
    [edits],
  )
  const [debounced, setDebounced] = useState<EditIn[]>(list)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(list), delayMs)
    return () => clearTimeout(t)
  }, [list, delayMs])

  const set = useCallback((doc: DocName, path: string, value: string | null, original: string | null) => {
    setEdits((prev) => {
      const next = new Map(prev)
      const key = fieldKey(doc, path)
      if (value === original) next.delete(key)
      else next.set(key, { doc, path, value })
      return next
    })
  }, [])

  const reset = useCallback((doc: DocName, path: string) => {
    setEdits((prev) => {
      const next = new Map(prev)
      next.delete(fieldKey(doc, path))
      return next
    })
  }, [])

  const get = useCallback((doc: DocName, path: string) => edits.get(fieldKey(doc, path)), [edits])

  const pending = list !== debounced
  return { list, debounced, pending, set, reset, get, count: edits.size }
}
