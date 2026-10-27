import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('director hides coming-soon skills and keeps them behind the active flag', async () => {
  const { visibleDirectorSkills } = await import('../src/components/Sidebar/DirectorChat.tsx')
  const skills = [
    { id: 'music', label: 'Music Video', active: true },
    { id: 'podcast', label: 'Video Podcast', active: false },
    { id: 'viral', label: 'Viral Video', active: false },
  ]
  assert.deepEqual(visibleDirectorSkills(skills).map(skill => skill.label), ['Music Video'])
  assert.deepEqual(skills.filter(skill => skill.active === false).map(skill => skill.label), ['Video Podcast', 'Viral Video'])
})

test('the director chooser does not offer Video Podcast or Viral Video', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { SkillSelector } = await import('../src/components/Sidebar/DirectorChat.tsx')
  try {
    render(<SkillSelector onSelect={() => undefined} />)
    assert.ok(screen.getByRole('button', { name: /Music Video/ }))
    assert.ok(screen.getByRole('button', { name: /Short Film/ }))
    assert.ok(screen.getByRole('button', { name: /Comic/ }))
    assert.equal(screen.queryByRole('button', { name: /Video Podcast/ }), null)
    assert.equal(screen.queryByRole('button', { name: /Viral Video/ }), null)
    assert.equal(screen.queryByText('Coming Soon'), null)
    assert.equal(screen.queryByText('Soon'), null)
  } finally {
    cleanup()
  }
})
