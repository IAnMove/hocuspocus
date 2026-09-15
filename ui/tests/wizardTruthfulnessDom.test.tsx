import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement, HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, MessageEvent: dom.window.MessageEvent,
  MutationObserver: dom.window.MutationObserver, React,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: () => undefined })
window.matchMedia = () => ({ matches: false }) as MediaQueryList
window.requestAnimationFrame = callback => { callback(0); return 1 }
window.cancelAnimationFrame = () => undefined

test('Wizard preserves semantic follow-up questions for varied series requests and after reload', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { AgentAssistantPanel } = await import('../src/features/agent/AgentAssistantPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  let messages: unknown[] = []
  let revision = 0
  let interpretations = 0
  let llmCalls = 0
  const unexpected: string[] = []
  const questions = ['¿De qué tratará tu serie y para qué público?', '¿Qué tienen en común esos personajes?', '¿Qué tono te gustaría explorar?']
  window.__HOCUSPOCUS_WIZARD_TRACE__ = []
  Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: class { addEventListener() {} close() {} } })
  const respond = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url.includes('/api/v1/wizard/workflows')) return respond({ version: 1, revision: 0, workflows: [] })
    if (url.includes('/api/v1/wizard/conversations')) {
      if (init?.method === 'PUT') { messages = JSON.parse(String(init.body)).conversation.messages; revision += 1 }
      return respond({ version: 1, revision, messages, executions: [] })
    }
    if (url.includes('/api/v1/outputs')) return respond({ outputs: [], total: 0 })
    if (url.includes('/api/v1/assets')) return respond({ assets: [], total: 0 })
    if (url.includes('/api/v1/llm/generate')) {
      const request = JSON.parse(String(init?.body))
      assert.ok(request.json_schema.required.includes('intent'))
      llmCalls += 1
      if (llmCalls === 1) return respond({ text: JSON.stringify({ reply: 'Invented completion.',
        actions: [{ type: 'open_tab', tab: 'images' }],
      }) })
      if (llmCalls === 2) {
        assert.match(request.prompt, /previous response did not contain a valid intent/)
        assert.match(request.prompt, /quiero hacer una serie de animacion/)
        assert.equal(useStore.getState().mediaFilter, 'all', 'the invalid plan must not execute before repair')
      }
      const index = interpretations++
      return respond({ text: JSON.stringify({ reply: 'He creado invented-series.', conversation_language: 'es',
        intent: { kind: 'clarification', execution: 'none', goal: 'Develop a recurring animated story', question: questions[index] },
        actions: index === 1 ? [] : [{ type: 'open_tab', tab: 'series_lab' }],
      }) })
    }
    unexpected.push(url)
    throw new Error(`Unexpected request: ${url}`)
  }
  useStore.setState({ activeWorkspace: 'semantic-series-dom', mediaFilter: 'all' })
  try {
    const panel = render(<AgentAssistantPanel workspace="semantic-series-dom" tasks={[]} onClose={() => undefined} />)
    const textarea = screen.getByPlaceholderText('Ask HocusPocus for a spell…')
    const requests = ['quiero hacer una serie de animacion', 'Unos personajes que vuelvan cada semana, algo asi', 'Me imagino ese mundo contado a lo largo de varios capitulos']
    for (const [index, request] of requests.entries()) {
      fireEvent.change(textarea, { target: { value: request } })
      fireEvent.submit(textarea.closest('form')!)
      await waitFor(() => assert.equal(window.__HOCUSPOCUS_WIZARD_TRACE__?.filter(item => item.results).length, index + 1))
      await waitFor(() => assert.equal((textarea as HTMLTextAreaElement).disabled, false))
      await waitFor(() => assert.ok(document.body.textContent?.includes(questions[index]),
        JSON.stringify({ body: document.body.textContent, turn: window.__HOCUSPOCUS_WIZARD_TRACE__?.at(-1)?.turn })))
      assert.doesNotMatch(document.body.textContent || '', /No action was executed|invented-series/)
    }
    assert.equal(interpretations, 3)
    assert.equal(llmCalls, 4, 'only the malformed first interpretation needs a repair request')
    assert.equal(useStore.getState().mediaFilter, 'series')
    assert.deepEqual(unexpected, [])
    await waitFor(() => assert.ok(JSON.stringify(messages).includes(questions[2])))
    panel.unmount()
    render(<AgentAssistantPanel workspace="semantic-series-dom" tasks={[]} onClose={() => undefined} />)
    await waitFor(() => assert.ok(document.body.textContent?.includes(questions[2])))
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: originalEventSource })
  }
})

for (const proposal of [
  { label: 'rejected create_story', actions: [{ type: 'create_story', title: 'Nightwatch' }], rejected: true },
  { label: 'empty actions', actions: [], rejected: false },
  { label: 'omitted actions', rejected: false },
]) test(`Wizard chat with ${proposal.label} persists no invented success`, { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { AgentAssistantPanel } = await import('../src/features/agent/AgentAssistantPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  let writes: unknown[] = []
  let revision = 0
  let llmCalls = 0
  const effects: string[] = []
  const question = 'Create a Story Lab project named Nightwatch using my settings.'
  window.__HOCUSPOCUS_WIZARD_TRACE__ = []
  Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: class { addEventListener() {} close() {} } })
  const respond = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    const method = init?.method || 'GET'
    if (url.includes('/api/v1/wizard/workflows')) return respond({ version: 1, revision: 0, workflows: [] })
    if (url.includes('/api/v1/wizard/conversations')) {
      if (method === 'PUT') { writes = JSON.parse(String(init?.body)).conversation.messages; revision += 1 }
      return respond({ version: 1, revision, messages: writes, executions: [] })
    }
    if (url.includes('/api/v1/outputs')) return respond({ outputs: [], total: 0 })
    if (url.includes('/api/v1/assets')) return respond({ assets: [], total: 0 })
    if (url.includes('/api/v1/llm/generate')) {
      llmCalls += 1
      return respond({ text: JSON.stringify({
        reply: 'I created story-invented-999 successfully.', conversation_language: 'en',
        ...('actions' in proposal ? { actions: proposal.actions } : {}),
      }) })
    }
    effects.push(`${method} ${url}`)
    throw new Error(`Unexpected effect: ${method} ${url}`)
  }
  useStore.setState({ activeWorkspace: 'truthfulness-dom', mediaFilter: 'all' })
  try {
    render(<AgentAssistantPanel workspace="truthfulness-dom" tasks={[]} onClose={() => undefined} />)
    const textarea = screen.getByPlaceholderText('Ask HocusPocus for a spell…')
    fireEvent.change(textarea, { target: { value: question } })
    fireEvent.submit(textarea.closest('form')!)
    await waitFor(() => assert.ok(window.__HOCUSPOCUS_WIZARD_TRACE__?.some(item => item.question === question && item.results)))
    await waitFor(() => assert.match(document.body.textContent || '', /No action was executed in this turn/))
    if (proposal.rejected) assert.match(document.body.textContent || '', /Actions not executed/)
    assert.doesNotMatch(document.body.textContent || '', /story-invented-999|successfully/)
    const trace = window.__HOCUSPOCUS_WIZARD_TRACE__!.find(item => item.question === question)!
    assert.deepEqual(trace.results, [])
    if (proposal.rejected) assert.equal((trace.turn as { rejections: { code: string }[] }).rejections[0].code, 'invalid_action')
    assert.deepEqual(effects, [])
    assert.equal(llmCalls, 2, 'invalid plans get one bounded repair attempt')
    await waitFor(() => assert.ok(JSON.stringify(writes).includes('No action was executed')))
    assert.doesNotMatch(JSON.stringify(writes), /story-invented-999/)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: originalEventSource })
  }
})
