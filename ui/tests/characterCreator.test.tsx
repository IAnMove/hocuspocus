import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import {
  buildAPrompt,
  buildCharacterOrbitPrompt,
  CHARACTER_ORBIT_VIEWS,
  CHARACTER_SHEET_RESOLUTION,
  needsVisionDescribe,
  viewCaptureTime,
} from '../src/features/characters/orbitPrompt.ts'

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

test('orbit prompt concatenates A keep/ignore lines with the official 360 B prompt', () => {
  const prompt = buildCharacterOrbitPrompt('character', [{ role: 'face' }, { role: 'outfit' }])
  assert.match(prompt, /<Picture 1> - keep only the face/)
  assert.match(prompt, /<Picture 2> - keep only the outfit/)
  assert.match(prompt, /Ignore body, wardrobe/)
  assert.match(prompt, /a full 360 degrees/)
  assert.match(prompt, /relaxed A-pose/)
  assert.match(prompt, /\[AUDIO\] Silence/)
  assert.doesNotMatch(prompt, /360-degree clockwise orbit/)
  assert.deepEqual(CHARACTER_ORBIT_VIEWS.map(view => view.id), ['front', 'left', 'back', 'right'])
  assert.deepEqual(CHARACTER_ORBIT_VIEWS.map(view => view.frame), [2, 21, 42, 63])
  assert.deepEqual(CHARACTER_ORBIT_VIEWS.map(view => view.hunyuan), ['front', 'left', 'back', 'right'])
  assert.equal(CHARACTER_SHEET_RESOLUTION, '768x1344')
  assert.equal(viewCaptureTime(24), 1)
})

test('a single object image is enough to build an orbit prompt', () => {
  const prompt = buildCharacterOrbitPrompt('object', [{ role: 'subject' }])
  assert.match(prompt, /<Picture 1>/)
  assert.doesNotMatch(prompt, /<Picture 2>/)
  assert.doesNotMatch(prompt, /A-pose/)
  assert.match(prompt, /turntable/)
})

test('A prompt can be overridden before concatenating B', () => {
  const prompt = buildCharacterOrbitPrompt(
    'character',
    [{ role: 'subject' }],
    '<Picture 1> - keep the bald head. Ignore the background.',
  )
  assert.match(prompt, /keep the bald head/)
  assert.doesNotMatch(prompt, /This is a subject reference only/)
  assert.match(prompt, /\[STAGING\]/)
})

test('A prompt names ignore lists per extra reference', () => {
  const a = buildAPrompt('character', [{ role: 'subject' }, { role: 'accessory' }])
  assert.match(a, /<Picture 2> - keep only this attached prop/)
})

test('empty A prompt means MiniMax should describe the image', () => {
  assert.equal(needsVisionDescribe(''), true)
  assert.equal(needsVisionDescribe('   '), true)
  assert.equal(needsVisionDescribe('<Picture 1> - keep the dwarf.'), false)
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

test('Character Creator captures 4 stills before Hunyuan, from one image', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { CharacterCreatorPanel } = await import('../src/features/characters/CharacterCreatorPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({
    models: [{ model_type: 'minimax_h3_ref2va' }],
    activeWorkspace: 'default',
    loadOutputs: async () => undefined,
  })
  try {
    render(<CharacterCreatorPanel />)
    assert.ok(screen.getByRole('button', { name: 'Objeto' }))
    assert.ok(screen.getByRole('button', { name: /Generar órbita 360/ }))
    assert.equal((screen.getByRole('button', { name: /Generar órbita 360/ }) as HTMLButtonElement).disabled, true)
    const hunyuan = screen.getByRole('button', { name: /Generar Hunyuan3D/ }) as HTMLButtonElement
    assert.equal(hunyuan.disabled, true)
    assert.ok(screen.getByText(/MiniMax describe/i))
    assert.ok(screen.getByText(/No hace falta escribir nada/i))
    assert.ok(screen.getByRole('button', { name: /A Prompt opcional/ }))
    assert.ok(screen.getByText(/Turbo LoRA/i))
    assert.ok(screen.getByText(/grabs 2 \/ 21 \/ 42 \/ 63/))
  } finally {
    cleanup()
  }
})
