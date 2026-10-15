// The SIMULATE pill is fixed over the centre of the top edge, above full-screen overlays (z-[100] over
// z-[60]). It intercepted the clicks meant for the Director dashboard header actions underneath.
import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MouseEvent: dom.window.MouseEvent, MutationObserver: dom.window.MutationObserver, React })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
window.matchMedia = (() => ({ matches: false, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia

async function renderBanner(executionMode: string) {
  const { render } = await import('@testing-library/react')
  const { ExecutionModeBanner } = await import('../src/components/ExecutionModeBanner.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { ensureUiI18n } = await import('../src/i18n/index.ts')
  ensureUiI18n().changeLanguage('en')
  useStore.setState({ systemConfig: { execution_mode: executionMode, execution_workspace: 'validation', execution_allow_paid: false } as never })
  return render(<ExecutionModeBanner />)
}

test('the simulation pill lets clicks through to the overlay underneath', async () => {
  const { cleanup } = await import('@testing-library/react')
  const view = await renderBanner('simulate')
  try {
    const pill = view.getByTestId('execution-mode-banner')
    assert.match(pill.className, /\bpointer-events-none\b/)
    assert.match(pill.textContent || '', /validation/)
  } finally { cleanup() }
})

test('real mode shows no pill', async () => {
  const { cleanup } = await import('@testing-library/react')
  const view = await renderBanner('real')
  try {
    assert.equal(view.queryByTestId('execution-mode-banner'), null)
  } finally { cleanup() }
})
