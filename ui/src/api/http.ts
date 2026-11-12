/** Same-origin in production; Vite proxy handles /api in development. */
export const BASE = ''

/** A non-2xx response. `status` lets callers tell a lost job (404) from an outage. */
export class HttpError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'HttpError'
    this.status = status
    this.detail = detail
  }
}

export function isHttpStatus(reason: unknown, status: number): boolean {
  return reason instanceof HttpError && reason.status === status
}

/** Build an HttpError from a failed response, preferring the backend `detail`. */
export async function httpError(res: Response, fallback: string): Promise<HttpError> {
  const body = await res.json().catch(() => null) as { detail?: unknown } | null
  const detail = typeof body?.detail === 'string' && body.detail ? body.detail : fallback
  return new HttpError(res.status, detail)
}
