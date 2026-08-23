import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from 'react'
import { KeyRound, LoaderCircle, ShieldCheck } from 'lucide-react'

type LanAuthStatus = {
  enabled: boolean
  required: boolean
  authenticated: boolean
}

type GateState = 'checking' | 'locked' | 'ready' | 'unreachable'

export function LanAuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>('checking')
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const checkAccess = useCallback(async () => {
    setState('checking')
    setError('')
    try {
      const response = await fetch('/api/v1/auth/lan/status', {
        credentials: 'same-origin',
        cache: 'no-store',
      })
      if (!response.ok) throw new Error(`Status request failed (${response.status})`)
      const status = await response.json() as LanAuthStatus
      setState(!status.required || status.authenticated ? 'ready' : 'locked')
    } catch {
      setError('Loreframe Lab could not reach its local server.')
      setState('unreachable')
    }
  }, [])

  useEffect(() => {
    void checkAccess()
  }, [checkAccess])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!token.trim() || submitting) return
    setSubmitting(true)
    setError('')
    try {
      const response = await fetch('/api/v1/auth/lan/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token.trim() }),
      })
      if (!response.ok) {
        setError(response.status === 401
          ? 'That LAN access token is not valid.'
          : `The server rejected the login (${response.status}).`)
        return
      }
      setToken('')
      setState('ready')
    } catch {
      setError('Loreframe Lab could not reach its local server.')
    } finally {
      setSubmitting(false)
    }
  }

  if (state === 'ready') return <>{children}</>

  return (
    <main className="h-full w-full bg-bg-primary text-text-primary flex items-center justify-center p-5">
      <section
        className="w-full max-w-md rounded-2xl border border-border bg-bg-secondary p-6 shadow-2xl"
        aria-labelledby="lan-auth-title"
      >
        <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-accent-blue/15 text-accent-blue">
          {state === 'checking'
            ? <LoaderCircle size={24} className="animate-spin" aria-hidden="true" />
            : <ShieldCheck size={24} aria-hidden="true" />}
        </div>
        <h1 id="lan-auth-title" className="text-xl font-semibold">Loreframe Lab LAN access</h1>

        {state === 'checking' ? (
          <p className="mt-2 text-sm text-text-secondary">Checking this device…</p>
        ) : state === 'unreachable' ? (
          <>
            <p className="mt-2 text-sm text-text-secondary">{error}</p>
            <button
              type="button"
              onClick={() => { void checkAccess() }}
              className="mt-5 w-full rounded-lg bg-accent-blue px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-blue-hover"
            >
              Retry
            </button>
          </>
        ) : (
          <form onSubmit={submit} className="mt-4">
            <p className="mb-4 text-sm text-text-secondary">
              Enter the session token shown in the Pinokio launch terminal. You only need to do this once per browser session.
            </p>
            {window.location.protocol !== 'https:' && (
              <p className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
                This LAN page is using unencrypted HTTP. Only enter the token on a network you trust.
              </p>
            )}
            <label htmlFor="lan-access-token" className="mb-1.5 block text-sm font-medium">
              LAN access token
            </label>
            <div className="relative">
              <KeyRound
                size={17}
                aria-hidden="true"
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
              />
              <input
                id="lan-access-token"
                type="password"
                value={token}
                onChange={event => setToken(event.target.value)}
                autoComplete="one-time-code"
                autoFocus
                className="w-full rounded-lg border border-border bg-bg-primary py-2.5 pl-10 pr-3 text-sm outline-none focus:border-accent-blue focus:ring-2 focus:ring-accent-blue/30"
              />
            </div>
            {error && <p role="alert" className="mt-2 text-sm text-red-400">{error}</p>}
            <button
              type="submit"
              disabled={!token.trim() || submitting}
              className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent-blue px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-blue-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting && <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />}
              Unlock this session
            </button>
          </form>
        )}
      </section>
    </main>
  )
}
