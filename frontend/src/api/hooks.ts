import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type EditIn } from './client'

export type StatusFilter = 'open' | 'approved' | 'rejected' | 'all'

export const keys = {
  meta: ['meta'] as const,
  cases: (status: StatusFilter) => ['cases', status] as const,
  case: (id: number) => ['case', id] as const,
  recheck: (id: number, edits: EditIn[]) => ['recheck', id, edits] as const,
}

export function useMeta() {
  return useQuery({
    queryKey: keys.meta,
    queryFn: async () => unwrap(await api.GET('/api/meta')),
    staleTime: Infinity,
  })
}

export function useCases(status: StatusFilter) {
  return useQuery({
    queryKey: keys.cases(status),
    queryFn: async () => unwrap(await api.GET('/api/reviews', { params: { query: { status } } })),
  })
}

export function useCase(id: number) {
  return useQuery({
    queryKey: keys.case(id),
    queryFn: async () =>
      unwrap(await api.GET('/api/reviews/{case_id}', { params: { path: { case_id: id } } })),
  })
}

/** Live re-check of the corrected values (writes nothing). Keeps the last answer on screen
 * while a new one is computed, so the panel doesn't flicker while typing. */
export function useRecheck(id: number, edits: EditIn[], enabled: boolean) {
  return useQuery({
    queryKey: keys.recheck(id, edits),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.POST('/api/reviews/{case_id}/recheck', {
          params: { path: { case_id: id } },
          body: { edits },
          signal,
        }),
      ),
    enabled,
    placeholderData: keepPreviousData,
    retry: false,
  })
}

function useInvalidateCase(id: number) {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['cases'] }),
      qc.invalidateQueries({ queryKey: keys.case(id) }),
    ])
}

export function useApprove(id: number) {
  const invalidate = useInvalidateCase(id)
  return useMutation({
    mutationFn: async (body: { edits: EditIn[]; reason: string | null }) =>
      unwrap(
        await api.POST('/api/reviews/{case_id}/approve', {
          params: { path: { case_id: id } },
          body,
        }),
      ),
    onSettled: invalidate,
  })
}

export function useReject(id: number) {
  const invalidate = useInvalidateCase(id)
  return useMutation({
    mutationFn: async (body: { edits: EditIn[]; reason: string }) =>
      unwrap(
        await api.POST('/api/reviews/{case_id}/reject', {
          params: { path: { case_id: id } },
          body,
        }),
      ),
    onSettled: invalidate,
  })
}
