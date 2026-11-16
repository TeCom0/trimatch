// Typed client for the review API. Types are generated from the FastAPI OpenAPI document:
//   npm run gen:api   (backend: `trimatch openapi frontend/openapi.json`)
import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']
export type CaseSummary = Schemas['CaseSummary']
export type CaseDetail = Schemas['CaseDetail']
export type FailedCheck = Schemas['FailedCheck']
export type RecheckOut = Schemas['RecheckOut']
export type ApproveOut = Schemas['ApproveOut']
export type RejectOut = Schemas['RejectOut']
export type Meta = Schemas['Meta']
export type EditIn = Schemas['EditIn']
export type DocName = EditIn['doc']
export type Box = Schemas['Box']
export type PoOut = Schemas['PoOut']

// fetch is looked up per request (not captured at import), so tests can stub it.
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  fetch: (req) => globalThis.fetch(req),
})

/** An API error with the server's message and, for 422/409, the checks that failed. */
export class ApiError extends Error {
  readonly status: number
  readonly checks: FailedCheck[]

  constructor(status: number, message: string, checks: FailedCheck[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.checks = checks
  }
}

type ErrorBody = { detail?: unknown; checks?: FailedCheck[] } | undefined

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI request validation errors
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join('.')}: ${d.msg}`)
      .join('; ')
  }
  return 'Unexpected error'
}

/** Unwrap an openapi-fetch result: data, or throw ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const body = result.error as ErrorBody
    throw new ApiError(
      result.response.status,
      detailText(body?.detail) || result.response.statusText,
      body?.checks ?? [],
    )
  }
  return result.data
}

export function pageUrl(caseId: number, doc: DocName, page: number): string {
  return `/api/reviews/${caseId}/documents/${doc}/pages/${page}`
}
