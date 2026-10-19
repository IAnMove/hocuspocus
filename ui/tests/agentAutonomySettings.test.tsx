import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, HTMLButtonElement: dom.window.HTMLButtonElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

test('«Modo un solo disparo» is off unless the server says one_shot and the switch flips between the two modes', async () => {
  const { render, screen, cleanup, fireEvent } = await import('@testing-library/react')
  const { AgentAutonomySettings } = await import('../src/features/agent/AgentAutonomySettings.tsx')
  const changes: Array<{ agent_autonomy?: string }> = []
  try {
    const view = render(<AgentAutonomySettings config={{}} onChange={change => changes.push(change)} />)
    const toggle = screen.getByRole('switch', { name: /Modo un solo disparo|One-shot mode/ })
    assert.equal(toggle.getAttribute('aria-checked'), 'false', 'a person approves unless the owner turns this on')
    assert.match(screen.getByText(/aprueba lo que normalmente aprueba una persona|approves what a person normally approves/).textContent!, /./)
    fireEvent.click(toggle)
    view.rerender(<AgentAutonomySettings config={{ agent_autonomy: 'one_shot' }} onChange={change => changes.push(change)} />)
    assert.equal(screen.getByRole('switch').getAttribute('aria-checked'), 'true')
    fireEvent.click(screen.getByRole('switch'))
    assert.deepEqual(changes, [{ agent_autonomy: 'one_shot' }, { agent_autonomy: 'review' }])
  } finally {
    cleanup()
  }
})

test('the switch is stored through the services config: one PUT with agent_autonomy, read back after', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const calls: Array<{ method: string; url: string; body?: unknown }> = []
  const server = { agent_autonomy: 'review' }
  const original = globalThis.fetch
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ method, url: String(input), ...(init?.body ? { body: JSON.parse(String(init.body)) } : {}) })
    if (method === 'PUT') { Object.assign(server, JSON.parse(String(init!.body))); return json({ status: 'ok', updated: { agent_autonomy: server.agent_autonomy } }) }
    return json({ ...server, workflow_parallelism_enabled: true, debug_trace_enabled: false, director_prompt_polish: 'off' })
  }) as typeof fetch
  try {
    await useStore.getState().loadServicesConfig()
    assert.equal(useStore.getState().servicesConfig?.agent_autonomy, 'review')
    await useStore.getState().updateServicesConfig({ agent_autonomy: 'one_shot' })
    const put = calls.find(call => call.method === 'PUT')!
    assert.ok(put.url.endsWith('/api/v1/services-config'))
    assert.deepEqual(put.body, { agent_autonomy: 'one_shot' })
    assert.equal(useStore.getState().servicesConfig?.agent_autonomy, 'one_shot')
  } finally {
    globalThis.fetch = original
  }
})
