import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createElement } from 'react'
import { act, render, cleanup } from '@testing-library/react'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('the raw prompts switch uses the visible title and the title toggles it', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const { ServicesSettingsPanel } = await import('../src/components/SettingsDrawer/ServicesSettingsPanel')
  const updates: Array<Record<string, unknown>> = []
  const initial = useStore.getState()
  useStore.setState({
    servicesConfigLoading: false,
    servicesConfig: { llm_provider: 'local', raw_prompts: false, show_experimental: false } as never,
    llmModels: [],
    llmStatus: null,
    systemConfig: {} as never,
    loadLlmModels: async () => {},
    updateSystemConfig: async () => {},
    updateServicesConfig: async (partial: Record<string, unknown>) => { updates.push(partial) },
  } as never)
  try {
    const view = render(createElement(ServicesSettingsPanel))
    const toggle = view.getByRole('switch', { name: 'Raw prompts' })
    assert.equal(toggle.getAttribute('aria-checked'), 'false')
    await act(async () => { view.getByText('Raw prompts').click() })
    assert.deepEqual(updates, [{ raw_prompts: true }])
  } finally {
    cleanup()
    useStore.setState(initial, true)
  }
})
