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
  return dom
}

installDom()

test('Story Lab navigation exposes every section in a scrollable mobile row', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { BookOpen, ImagePlus, Music } = await import('lucide-react')
  const { StoryLabNavigation } = await import('../src/features/stories/StoryLabNavigation.tsx')
  const tabs = [
    { id: 'overview', label: 'Story', icon: BookOpen },
    { id: 'assets', label: 'Assets', icon: ImagePlus },
    { id: 'music', label: 'Music', icon: Music },
  ] as const
  let selected = 'overview'
  const view = render(
    <StoryLabNavigation
      tabs={[...tabs]}
      activeTab={selected}
      onChange={tab => { selected = tab }}
      notes={<p>Desktop guidance</p>}
    />,
  )

  const navigation = screen.getByRole('navigation', { name: 'Story Lab sections' })
  assert.match(navigation.className, /w-full/)
  assert.match(navigation.className, /overflow-x-auto/)
  assert.match(navigation.className, /md:flex-col/)
  assert.match(navigation.className, /md:overflow-y-auto/)
  assert.equal(screen.getAllByRole('button').length, tabs.length)
  assert.equal(screen.getByRole('button', { name: 'Story' }).getAttribute('aria-current'), 'page')
  assert.equal(screen.getByText('Desliza para más secciones').getAttribute('aria-hidden'), 'true')
  assert.match(screen.getByText('Desktop guidance').parentElement?.className || '', /hidden/)

  fireEvent.click(screen.getByRole('button', { name: 'Music' }))
  assert.equal(selected, 'music')
  view.rerender(
    <StoryLabNavigation
      tabs={[...tabs]}
      activeTab={selected}
      onChange={tab => { selected = tab }}
      notes={<p>Desktop guidance</p>}
    />,
  )
  assert.equal(screen.getByRole('button', { name: 'Music' }).getAttribute('aria-current'), 'page')
  cleanup()
})
