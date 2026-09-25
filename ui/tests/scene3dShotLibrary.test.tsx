import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    React,
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLCanvasElement: dom.window.HTMLCanvasElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    KeyboardEvent: dom.window.KeyboardEvent,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
    getComputedStyle: dom.window.getComputedStyle,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

test.afterEach(() => { window.localStorage.clear() })

async function openLibrary(overrides: Record<string, unknown> = {}) {
  const { render } = await import('@testing-library/react')
  const { Scene3DShotLibraryDialog } = await import('../src/features/scene3d/Scene3DShotLibrary')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  const calls = { templates: [] as string[], packs: [] as string[], closed: 0 }
  render(<Scene3DShotLibraryDialog document={applyScene3DTemplate('two-shot')} applyDisabled={false} editingLocked={false} keepAssets onKeepAssets={() => {}}
    onTemplate={id => calls.templates.push(id)} onUserTemplate={pack => calls.packs.push(pack.id)} onClose={() => { calls.closed++ }} {...overrides} />)
  return calls
}

test('the shot library filters by Action and by set, and a click only picks a shot', async () => {
  const { screen, fireEvent, cleanup } = await import('@testing-library/react')
  try {
    const calls = await openLibrary()
    fireEvent.click(screen.getByRole('button', { name: 'Action' }))
    assert.ok(screen.getByTestId('world3d-template-sea-deck'))
    assert.ok(screen.getByTestId('world3d-template-jungle-ambush'))
    assert.equal(screen.queryByTestId('world3d-template-two-shot'), null)
    fireEvent.click(screen.getByRole('button', { name: 'Sea' }))
    assert.equal(screen.queryByTestId('world3d-template-jungle-ambush'), null)
    fireEvent.click(screen.getByTestId('world3d-template-sea-deck'))
    assert.deepEqual(calls.templates, [], 'picking does not replace the scene')
    assert.equal(screen.getByTestId('world3d-template-sea-deck').getAttribute('aria-pressed'), 'true')
    fireEvent.click(screen.getByTestId('world3d-use-shot'))
    assert.deepEqual(calls.templates, ['sea-deck'])
    assert.equal(calls.closed, 1)
  } finally {
    cleanup()
  }
})

test('double-click and Enter use a shot straight away, and it shows up under Recent', async () => {
  const { screen, fireEvent, cleanup } = await import('@testing-library/react')
  try {
    const calls = await openLibrary()
    assert.equal(screen.queryByRole('button', { name: 'Recent' }), null, 'no recents yet')
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search templates' }), { target: { value: 'close' } })
    fireEvent.doubleClick(screen.getByTestId('world3d-template-face-closeup'))
    const card = screen.getAllByRole('button').find(button => button.dataset.testid?.startsWith('world3d-template-') && button.dataset.testid !== 'world3d-template-face-closeup')!
    card.focus()
    fireEvent.keyDown(card, { key: 'Enter' })
    assert.equal(calls.templates[0], 'face-closeup')
    assert.equal(calls.templates.length, 2)
    cleanup()
    await openLibrary()
    assert.equal(screen.getByRole('searchbox', { name: 'Search templates' }).getAttribute('value'), 'close', 'the search is remembered')
    fireEvent.click(screen.getByRole('button', { name: 'Recent' }))
    assert.equal(screen.getAllByRole('button').filter(button => button.dataset.testid?.startsWith('world3d-template-'))[0].dataset.testid, `world3d-template-${calls.templates[1]}`, 'newest first')
  } finally {
    cleanup()
  }
})

test('while exporting the library can be browsed but not applied', async () => {
  const { screen, fireEvent, cleanup } = await import('@testing-library/react')
  try {
    const calls = await openLibrary({ applyDisabled: true })
    fireEvent.doubleClick(screen.getByTestId('world3d-template-sea-deck'))
    assert.equal((screen.getByTestId('world3d-use-shot') as HTMLButtonElement).disabled, true)
    assert.deepEqual(calls.templates, [])
  } finally {
    cleanup()
  }
})

test('my scenarios live in the library: pick one, then use it', async () => {
  const { screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { createUserTemplate, saveUserTemplate } = await import('../src/features/scene3d/userTemplates')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  const pack = createUserTemplate({ document: applyScene3DTemplate('cafe-dance'), title: 'Harbor cafe', description: '', includeAssets: false })!
  saveUserTemplate(pack)
  try {
    const calls = await openLibrary()
    fireEvent.click(screen.getByRole('button', { name: 'My scenarios' }))
    fireEvent.click(screen.getByRole('button', { name: 'Harbor cafe' }))
    assert.deepEqual(calls.packs, [])
    assert.match(screen.getByTestId('world3d-shot-preview').textContent ?? '', /Harbor cafe/)
    fireEvent.click(screen.getByTestId('world3d-use-shot'))
    assert.deepEqual(calls.packs, [pack.id])
  } finally {
    cleanup()
  }
})

test('arrow keys move through the grid by rows and columns', async () => {
  const { gridFocusTarget } = await import('../src/features/scene3d/shotLibraryState')
  assert.equal(gridFocusTarget(5, 'ArrowRight', 12, 4), 6)
  assert.equal(gridFocusTarget(5, 'ArrowDown', 12, 4), 9)
  assert.equal(gridFocusTarget(1, 'ArrowUp', 12, 4), 1, 'stays put at the edge')
  assert.equal(gridFocusTarget(3, 'End', 12, 4), 11)
  assert.equal(gridFocusTarget(3, 'Tab', 12, 4), undefined)
})

test('the saved view and recents survive bad or stale storage', async () => {
  const { readLibraryView, readRecentShots, rememberRecentShot } = await import('../src/features/scene3d/shotLibraryState')
  window.localStorage.setItem('hocuspocus.shotLibrary.view', '{"category":"nope","setting":"mars","query":7}')
  assert.deepEqual(readLibraryView(), { category: 'all', setting: 'all', query: '' })
  window.localStorage.setItem('hocuspocus.shotLibrary.recent', '["gone-template","sea-deck"]')
  assert.deepEqual(readRecentShots(), ['sea-deck'])
  assert.deepEqual(rememberRecentShot('two-shot'), ['two-shot', 'sea-deck'])
})
