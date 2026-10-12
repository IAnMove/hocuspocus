const REPORT_ENDPOINT = '/api/v1/debug/user-action'

/** Log a render error and, when debug tracing is on, record it server-side.
 *  The endpoint stores short control strings only; it answers `disabled` otherwise. */
export function reportUiError(error: unknown, origin: string, componentStack?: string | null): void {
  console.error(`[ui] ${origin}:`, error, componentStack ?? '')
  if (typeof fetch !== 'function' || typeof window === 'undefined') return
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error)
  void fetch(REPORT_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      control: message.slice(0, 500),
      control_type: origin.slice(0, 80),
      view: window.location.pathname,
    }),
    keepalive: true,
  }).catch(() => undefined)
}

export function describeError(error: unknown): string {
  if (error instanceof Error) return error.stack || `${error.name}: ${error.message}`
  return String(error)
}
