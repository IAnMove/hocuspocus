import { useEffect, useId, useRef, useState } from 'react'
import { Info } from 'lucide-react'
import { useUiTranslation } from '../../i18n'

type Status = { enabled: boolean; managedByEnvironment: boolean; endpoint: string; token?: string }
async function responseJson(response: Response, fallback: string) {
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : body.detail?.message
    throw new Error(typeof detail === 'string' ? detail : `${fallback} (HTTP ${response.status})`)
  }
  return body
}

async function copyToken(value: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(value); return true } catch { /* Try the local fallback. */ }
  }
  const field = document.createElement('textarea')
  const previousFocus = document.activeElement
  field.value = value
  field.readOnly = true
  field.style.position = 'fixed'
  field.style.opacity = '0'
  field.setAttribute('aria-hidden', 'true')
  document.body.appendChild(field)
  try { field.focus(); field.select(); return document.execCommand?.('copy') === true } catch { return false }
  finally { field.remove(); if (previousFocus instanceof HTMLElement) previousFocus.focus() }
}

function McpTokenField({ token }: { token: string }) {
  const { t } = useUiTranslation('settings')
  const ref = useRef<HTMLInputElement>(null)
  const [visible, setVisible] = useState(false)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'manual'>('idle')
  const id = useId()
  useEffect(() => {
    if (copyState === 'manual') { ref.current?.focus(); ref.current?.select() }
  }, [copyState])
  const copy = async () => {
    const copied = await copyToken(token)
    setCopyState(copied ? 'copied' : 'manual')
    if (!copied) { setVisible(true); ref.current?.focus(); ref.current?.select() }
  }
  return <div className="space-y-2 text-xs">
    <label htmlFor={id}>{t('mcp.token')}</label>
    <input id={id} ref={ref} type={visible ? 'text' : 'password'} readOnly value={token} spellCheck={false} autoComplete="off" className="w-full rounded border border-border bg-bg-tertiary p-2" />
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={() => void copy()} className="min-h-11 rounded border border-border px-3">{t('mcp.copyToken')}</button>
      <button type="button" onClick={() => setVisible(value => !value)} aria-pressed={visible} className="min-h-11 rounded border border-border px-3">{t(visible ? 'mcp.hideToken' : 'mcp.showToken')}</button>
    </div>
    {copyState !== 'idle' && <p role="status">{t(copyState === 'copied' ? 'mcp.copied' : 'mcp.copyFailed')}</p>}
  </div>
}

type Diagnostic = { profile: string; server?: string; protocol?: string; toolCount?: number }
function McpDiagnostics({ endpoint, token, enabled }: { endpoint: string; token: string; enabled: boolean }) {
  const { t } = useUiTranslation('settings')
  const [result, setResult] = useState<Diagnostic | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const check = async () => {
    setBusy(true); setError(''); setResult(null)
    try {
      const capabilities = await responseJson(await fetch('/api/v1/system/capabilities'), t('mcp.failed'))
      const next: Diagnostic = { profile: String(capabilities.profile || t('mcp.unknownProfile')) }
      if (enabled && token) {
        const rpc = async (method: string, params?: Record<string, unknown>) => {
          const response = await responseJson(await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ jsonrpc: '2.0', id: method, method, params }) }), t('mcp.failed'))
          if (response.error) throw new Error(String(response.error.message || t('mcp.failed')))
          return response.result
        }
        const identity = await rpc('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'hocuspocus-settings', version: '1' } })
        const initialized = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) })
        if (!initialized.ok) await responseJson(initialized, t('mcp.failed'))
        const catalog = await rpc('tools/list')
        if (!Array.isArray(catalog?.tools)) throw new Error(t('mcp.failed'))
        next.server = String(identity.serverInfo?.name || '')
        next.protocol = String(identity.protocolVersion || '')
        next.toolCount = catalog.tools.length
      }
      setResult(next)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  return <div className="space-y-2 text-xs">
    <button type="button" disabled={busy} onClick={() => void check()} className="min-h-11 rounded border border-border px-3">{t(busy ? 'mcp.checking' : 'mcp.check')}</button>
    {result && <div role="status" className="space-y-1 [overflow-wrap:anywhere]">
      <p>{t('mcp.profile', { profile: result.profile })}</p>
      {result.toolCount != null ? <><p>{t('mcp.connected', { server: result.server, protocol: result.protocol, count: result.toolCount })}</p><p>{t('mcp.authVerified')}</p></> : <p>{t('mcp.tokenUnavailable')}</p>}
    </div>}
    {error && <p role="alert" className="text-red-300">{error}</p>}
  </div>
}

export function McpSettingsPanel() {
  const { t } = useUiTranslation('settings')
  const [status, setStatus] = useState<Status | null>(null), [busy, setBusy] = useState(false)
  const [error, setError] = useState(''), [token, setToken] = useState(''), [help, setHelp] = useState(false)
  const id = useId()
  useEffect(() => {
    const abort = new AbortController()
    void fetch('/api/v1/settings/mcp', { signal: abort.signal }).then(async response => {
      setStatus(await responseJson(response, t('mcp.failed')) as Status)
    }).catch(e => { if (!abort.signal.aborted) setError(String(e)) })
    return () => abort.abort()
  }, [t])
  const update = async (enabled: boolean, rotate = false) => {
    setBusy(true); setError('')
    try {
      const response = await fetch('/api/v1/settings/mcp', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled, rotate }) })
      const next = await responseJson(response, t('mcp.failed')) as Status
      setStatus(next); if (next.token) setToken(next.token)
      if (!enabled) setToken('')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const endpoint = status ? new URL(status.endpoint, window.location.origin).href : ''
  return <section className="space-y-3 rounded-lg border border-border p-3" data-testid="mcp-settings">
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">{t('mcp.title')}</h3>
      <button type="button" aria-label={t('mcp.info')} aria-expanded={help} aria-controls={id} onMouseEnter={() => setHelp(true)} onMouseLeave={() => setHelp(false)} onFocus={() => setHelp(true)} onBlur={() => setHelp(false)} onClick={() => setHelp(true)} onKeyDown={event => { if (event.key === 'Escape') setHelp(false) }} className="min-h-9 min-w-9"><Info size={18} /></button>
    </div>
    {help && <div id={id} role="tooltip" className="space-y-2 rounded border border-border bg-bg-tertiary p-3 text-xs leading-relaxed">
      <p>{t('mcp.help')}</p><p>{t('mcp.access')}</p><p>{t('mcp.use')}</p>
    </div>}
    <p className="text-xs text-text-muted">{t('mcp.summary')}</p>
    <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" disabled={!status || busy} checked={status?.enabled ?? false} onChange={e => void update(e.target.checked)} />{t('mcp.enable')}</label>
    {status && <>
      <label className="block text-xs">{t('mcp.endpoint')}<input readOnly value={endpoint} className="mt-1 w-full rounded border border-border bg-bg-tertiary p-2" /></label>
      {status.managedByEnvironment && <p className="text-xs">{t('mcp.environment')}</p>}
      {token && <McpTokenField key={token} token={token} />}
      <McpDiagnostics key={`${status.enabled}:${token}`} endpoint={endpoint} token={token} enabled={status.enabled} />
      <details className="text-xs"><summary className="min-h-9 cursor-pointer">{t('mcp.example')}</summary><pre className="overflow-x-auto rounded bg-bg-tertiary p-2">{JSON.stringify({ mcpServers: { hocuspocus: { url: endpoint, headers: { Authorization: 'Bearer <YOUR_TOKEN>' } } } }, null, 2)}</pre><p className="mt-2">{t('mcp.client')}</p></details>
      {status.enabled && !status.managedByEnvironment && <button type="button" disabled={busy} onClick={() => void update(true, true)} className="min-h-9 rounded border border-border px-2 text-xs">{t('mcp.rotate')}</button>}
    </>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </section>
}
