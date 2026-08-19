import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { buildCharacterOrbitPrompt, CHARACTER_ORBIT_VIEWS } from '../src/features/characters/orbitPrompt.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
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
}

installDom()

test('orbit prompt keeps face and outfit as separate H3 subjects', () => {
  const prompt = buildCharacterOrbitPrompt()
  assert.match(prompt, /subject_definitions:/)
  assert.match(prompt, /<Picture 1>/)
  assert.match(prompt, /<Picture 2>/)
  assert.match(prompt, /360-degree clockwise orbit/)
  assert.match(prompt, /fully_preserved/)
  assert.match(prompt, /non_diegetic_music: N\/A/)
  assert.deepEqual(CHARACTER_ORBIT_VIEWS.map(view => view.id), ['front', 'right', 'back', 'left'])
})

test('Character Creator tab sits next to Workspaces', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ mediaFilter: 'all', outputSearchQuery: '' })
  try {
    render(<TabFilter />)
    assert.ok(screen.getByRole('tab', { name: /Workspaces/ }))
    assert.ok(screen.getByRole('tab', { name: /Character Creator/ }))
  } finally {
    cleanup()
  }
})
