import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://192.168.1.9:8080/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
const { ensureUiI18n } = await import('../src/i18n/index.ts')
await ensureUiI18n().changeLanguage('en')
const { McpSettingsPanel } = await import('../src/components/SettingsDrawer/McpSettingsPanel.tsx')
const token = 'isolated-ui-test-token'
const status = { enabled: false, managedByEnvironment: false, endpoint: '/api/v1/mcp' }
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })

async function enabledPanel() {
  render(<McpSettingsPanel />)
  await waitFor(() => assert.equal((screen.getByRole('checkbox') as HTMLInputElement).disabled, false))
  fireEvent.click(screen.getByRole('checkbox'))
  return await screen.findByLabelText('New token — copy before closing Settings') as HTMLInputElement
}

for (const mode of ['clipboard', 'fallback', 'denied', 'manual'] as const) {
  test(`MCP token copy supports ${mode} without requiring HTTPS`, async () => {
    const originalFetch = globalThis.fetch
    const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
    const originalExec = document.execCommand
    let copied = ''
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: mode === 'clipboard' ? { writeText: async (value: string) => { copied = value } } : mode === 'denied' ? { writeText: async () => { throw new Error('Copy denied') } } : undefined })
    document.execCommand = () => {
      if (mode === 'fallback' || mode === 'denied') { copied = document.querySelector('textarea')!.value; return true }
      return false
    }
    globalThis.fetch = async (_url, init) => json(init?.method === 'PUT' ? { ...status, enabled: true, token } : status)
    try {
      const input = await enabledPanel()
      assert.equal(input.type, 'password')
      fireEvent.click(screen.getByRole('button', { name: 'Copy token' }))
      if (mode === 'manual') {
        await screen.findByText('Could not copy the token. Select and copy the field manually.')
        assert.equal(input.type, 'text')
        assert.equal(input.selectionStart, 0)
        assert.equal(input.selectionEnd, token.length)
        assert.ok(document.activeElement === input)
        fireEvent.click(screen.getByRole('button', { name: 'Hide token' }))
        assert.equal(input.type, 'password')
      } else {
        await screen.findByText('Token copied.')
        assert.ok(copied === token)
        assert.equal(input.type, 'password')
      }
      assert.equal(document.querySelector('textarea'), null)
      assert.equal(screen.queryByRole('alert'), null)
    } finally {
      cleanup(); globalThis.fetch = originalFetch; document.execCommand = originalExec
      if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard)
      else Reflect.deleteProperty(navigator, 'clipboard')
    }
  })
}

test('MCP settings preserve the server explanation when an update is rejected', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (_url, init) => init?.method === 'PUT' ? json({ detail: 'Open settings at the local application address.' }, 403) : json(status)
  try {
    render(<McpSettingsPanel />)
    await waitFor(() => assert.equal((screen.getByRole('checkbox') as HTMLInputElement).disabled, false))
    fireEvent.click(screen.getByRole('checkbox'))
    await screen.findByText('Open settings at the local application address.')
    assert.equal((screen.getByRole('checkbox') as HTMLInputElement).checked, false)
  } finally { cleanup(); globalThis.fetch = originalFetch }
})

test('MCP diagnostics verify discovery with the issued token and never execute a tool', async () => {
  const originalFetch = globalThis.fetch
  const methods: string[] = []
  globalThis.fetch = async (url, init) => {
    if (String(url).endsWith('/system/capabilities')) return json({ profile: 'core' })
    if (String(url).endsWith('/settings/mcp')) return json(init?.method === 'PUT' ? { ...status, enabled: true, token } : status)
    const body = JSON.parse(String(init?.body))
    assert.ok(new Headers(init?.headers).get('Authorization') === `Bearer ${token}`)
    methods.push(body.method)
    if (body.method === 'notifications/initialized') {
      assert.equal('id' in body, false)
      return new Response(null, { status: 202 })
    }
    if (body.method === 'initialize') assert.equal(body.params.clientInfo.name, 'hocuspocus-settings')
    return json({ jsonrpc: '2.0', id: body.id, result: body.method === 'initialize' ? { serverInfo: { name: 'hocuspocus-core' }, protocolVersion: '2025-03-26' } : { tools: [{ name: 'assets' }] } })
  }
  try {
    await enabledPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Check connection' }))
    await screen.findByText('Authentication and tool discovery verified. No tools were executed.')
    assert.deepEqual(methods, ['initialize', 'notifications/initialized', 'tools/list'])
    assert.ok(screen.getByText('Runtime profile: core'))
    assert.ok(screen.getByText('hocuspocus-core · protocol 2025-03-26 · 1 tools'))
  } finally { cleanup(); globalThis.fetch = originalFetch }
})

test('MCP diagnostics disclose the verification limit for environment-managed tokens', async () => {
  const originalFetch = globalThis.fetch
  const calls: string[] = []
  globalThis.fetch = async (url, init) => {
    calls.push(`${init?.method || 'GET'} ${url}`)
    return json(String(url).endsWith('/system/capabilities') ? { profile: 'nvidia' } : { ...status, enabled: true, managedByEnvironment: true })
  }
  try {
    render(<McpSettingsPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Check connection' }))
    await screen.findByText('Profile checked. Authentication and tools were not checked because no enabled token is available in this Settings session.')
    assert.equal(calls.some(call => call.startsWith('PUT') || call.startsWith('POST')), false)
    assert.equal(screen.queryByText('Authentication and tool discovery verified. No tools were executed.'), null)
  } finally { cleanup(); globalThis.fetch = originalFetch }
})
