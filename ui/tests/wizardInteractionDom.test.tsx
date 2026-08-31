import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    Event: dom.window.Event,
    MessageEvent: dom.window.MessageEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
    React,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: () => undefined,
  })
  dom.window.requestAnimationFrame = callback => {
    callback(0)
    return 1
  }
  dom.window.cancelAnimationFrame = () => undefined
  return dom
}

class QuietEventSource {
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  addEventListener() {}

  close() {}
}

function pendingWorkflow() {
  return {
    workflowId: 'workflow-dom-reload',
    type: 'story_music_video',
    workspace: 'default',
    userRequest: 'Prepara un videoclip con el audio canónico',
    state: 'awaiting_input',
    currentStep: 0,
    steps: [{
      stepId: 'attach-audio',
      kind: 'attach audio',
      state: 'awaiting_input',
      input: {},
      output: {},
      taskId: '',
      pipelineId: '',
      outputRefs: [],
      executionKey: 'default|story_music_video:attach-audio|workflow-dom-reload|{}',
      startedAt: 1,
      completedAt: 0,
      attempts: 1,
      error: '',
    }],
    resolvedEntityIds: { storyId: 'story-dom' },
    inputSnapshot: {},
    taskIds: [],
    pipelineIds: [],
    outputRefs: [],
    confirmationScope: [],
    processedEventIds: [],
    attempts: 1,
    createdAt: 1,
    updatedAt: 1,
    recoverableError: '',
    cancelRequested: false,
    resumeRequested: false,
    pendingInput: {
      workflowId: 'workflow-dom-reload',
      stepId: 'attach-audio',
      reason: 'Elige la canción exacta para continuar.',
      fields: ['audio.outputName'],
      options: [{ value: 'himno-v2.wav', label: 'Himno v2' }],
      recommended: 'himno-v2.wav',
      resolvedEntityIds: { storyId: 'story-dom' },
      answer: null,
      version: 1,
      requestedAt: 1,
      createdAt: 1,
      updatedAt: 1,
      answeredAt: 0,
    },
  }
}

installDom()

test('Wizard DOM interaction navigates, accepts form input, and restores a pending choice after reload', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { AgentAssistantPanel } = await import('../src/features/agent/AgentAssistantPanel.tsx')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  const workflow = pendingWorkflow()
  let workflowWrites = 0

  Object.defineProperty(globalThis, 'EventSource', {
    configurable: true,
    value: QuietEventSource,
  })
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    const method = init?.method || 'GET'
    if (url.includes('/api/v1/wizard/workflows')) {
      if (method === 'PUT') {
        workflowWrites += 1
        return new Response(JSON.stringify({ version: 1, revision: workflowWrites, workflows: [workflow] }), {
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ version: 1, revision: workflowWrites, workflows: [workflow] }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.includes('/api/v1/wizard/conversations')) {
      return new Response(JSON.stringify({ version: 1, revision: 0, messages: [], executions: [] }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.includes('/api/v1/outputs')) {
      return new Response(JSON.stringify({ outputs: [], total: 0 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected Wizard request: ${method} ${url}`)
  }

  useStore.setState({ mediaFilter: 'all', developerMode: false, outputSearchQuery: '' })
  try {
    const tabs = render(<TabFilter />)
    fireEvent.click(screen.getByRole('tab', { name: /Series Lab/ }))
    assert.equal(useStore.getState().mediaFilter, 'series')
    assert.equal(screen.getByRole('tab', { name: /Series Lab/ }).getAttribute('aria-selected'), 'true')
    fireEvent.click(screen.getByTitle('Search outputs'))
    const search = screen.getByPlaceholderText('Search...') as HTMLInputElement
    fireEvent.change(search, { target: { value: 'himno' } })
    assert.equal(search.value, 'himno')
    tabs.unmount()

    const first = render(<AgentAssistantPanel workspace="default" tasks={[]} onClose={() => undefined} />)
    const pending = await screen.findByRole('group', { name: 'Wizard pending question' })
    assert.match(pending.textContent || '', /Elige la canción exacta/)
    assert.ok(screen.getByRole('button', { name: 'Himno v2 · recomendado' }))
    const textarea = screen.getByPlaceholderText('Pide un hechizo en HocusPocus…') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: 'usa el audio recomendado' } })
    assert.equal(textarea.value, 'usa el audio recomendado')

    // A browser reload must rehydrate the same durable question instead of
    // silently turning it into a new LLM turn.
    first.unmount()
    const second = render(<AgentAssistantPanel workspace="default" tasks={[]} onClose={() => undefined} />)
    await screen.findByRole('group', { name: 'Wizard pending question' })
    fireEvent.click(screen.getByRole('button', { name: 'Himno v2 · recomendado' }))
    await waitFor(() => assert.ok(workflowWrites > 0))
    second.unmount()
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', {
      configurable: true,
      value: originalEventSource,
    })
  }
})
