import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('Wizard presentation exposes semantic capability anchors, without CSS selectors', async () => {
  const { listCapabilities } = await import('../src/features/agent/capabilityRegistry.ts')
  const definitions = listCapabilities()
  assert.ok(definitions.length > 0)
  for (const definition of definitions) {
    assert.ok(definition.presentation?.destination, `${definition.name} needs a presentation destination`)
    assert.ok(Array.isArray(definition.presentation?.anchors), `${definition.name} needs presentation anchors`)
    for (const anchor of definition.presentation?.anchors || []) {
      assert.match(anchor, /^[a-z][a-z0-9_-]*$/, `${definition.name} has a non-semantic anchor: ${anchor}`)
    }
  }
})

test('Wizard avatar state is visible to assistive technology without leaking decorative nodes', async () => {
  const React = (await import('react')).default
  globalThis.React = React
  const { render, cleanup } = await import('@testing-library/react')
  const { AgentAvatar } = await import('../src/features/agent/AgentAvatar.tsx')
  try {
    const { container } = render(React.createElement(AgentAvatar, { state: 'acting', size: 48 }))
    const avatar = container.querySelector('.hp-agent-avatar')
    assert.ok(avatar)
    assert.equal(avatar.getAttribute('data-state'), 'acting')
    assert.equal(avatar.getAttribute('aria-hidden'), 'true')
    assert.equal(avatar.style.getPropertyValue('--hp-agent-size'), '48px')
    assert.equal(avatar.querySelectorAll('.hp-agent-mote').length, 3)
    assert.equal(avatar.querySelector('img')?.getAttribute('alt'), '')
  } finally {
    cleanup()
  }
})

test('Wizard panel keeps dialog, live-region and pending-question ARIA contracts', async () => {
  const panelSource = await readFile(new URL('../src/features/agent/AgentAssistantPanel.tsx', import.meta.url), 'utf8')
  assert.match(panelSource, /function agentPanelPresentation/)
  assert.match(panelSource, /return \{ role: 'region' as const, ariaModal: undefined, autoFocus: false \}/)
  assert.match(panelSource, /role=\{panelPresentation\.role\}/)
  assert.match(panelSource, /aria-modal=\{panelPresentation\.ariaModal\}/)
  assert.match(panelSource, /autoFocus=\{panelPresentation\.autoFocus\}/)
  assert.match(panelSource, /aria-live="polite"/)
  assert.match(panelSource, /role="group" aria-label="Wizard pending question"/)
  assert.match(panelSource, /aria-label=\{t\('title'\)\}/)
})

test('Wizard magic animations have a reduced-motion escape hatch', async () => {
  const css = await readFile(new URL('../src/index.css', import.meta.url), 'utf8')
  const reducedMotionBlocks = [...css.matchAll(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/g)]
  assert.ok(reducedMotionBlocks.length >= 2, 'intro and Wizard reduced-motion contracts should both exist')
  const wizardBlock = reducedMotionBlocks.at(-1)?.[1] || ''
  for (const selector of ['.hp-agent-avatar img', '.hp-agent-halo', '.hp-agent-mote', '.hp-agent-panel']) {
    assert.match(wizardBlock, new RegExp(selector.replace(/[.-]/g, '\\$&')))
  }
  assert.match(wizardBlock, /animation:\s*none/)
})
