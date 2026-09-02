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
import {
  attachCharacterCreatorMesh,
  attachCharacterCreatorMeshForWorkspace,
  characterCreatorHistoryKey,
  parseCharacterCreatorHistory,
  rememberCharacterCreatorSheet,
  rememberCharacterCreatorSheetForWorkspace,
} from '../src/features/characters/characterCreatorHistory.ts'

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
  assert.match(prompt, /\[0-3 seconds\].*full 360 degrees/)
  assert.match(prompt, /exact same pose/)
  assert.match(prompt, /then locked off and static/)
  assert.match(prompt, /rotates as one rigid object/)
  assert.match(prompt, /\[3-4 seconds\].*push-in/)
  assert.match(prompt, /\[4-5 seconds\].*whip-pan/)
  assert.match(prompt, /full 360 degrees/)
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

test('Character Creator history writes the origin workspace store, not the in-memory list of another workspace', () => {
  const store = new Map<string, string>()
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value) },
  }
  const luma = {
    id: 'luma',
    name: 'Luma',
    kind: 'character' as const,
    videoName: 'luma-orbit.mp4',
    views: [{ id: 'front', hunyuan: 'front' as const, label: 'Front', filename: 'luma-front.png', url: '/luma-front.png', time: 0.1 }],
    workspace: 'cast-a',
    createdAt: '2026-08-29T00:00:00Z',
  }
  const brin = {
    id: 'brin',
    name: 'Brin',
    kind: 'character' as const,
    videoName: 'brin-orbit.mp4',
    views: [],
    workspace: 'cast-b',
    createdAt: '2026-08-29T01:00:00Z',
  }
  rememberCharacterCreatorSheetForWorkspace(storage, 'cast-a', luma)
  rememberCharacterCreatorSheetForWorkspace(storage, 'cast-b', brin)

  const lateSheet = {
    id: 'luma-late',
    name: 'Luma late',
    kind: 'character' as const,
    videoName: 'luma-late.mp4',
    views: [],
    workspace: 'cast-a',
    createdAt: '2026-08-29T02:00:00Z',
  }
  const nextA = rememberCharacterCreatorSheetForWorkspace(storage, 'cast-a', lateSheet)
  assert.deepEqual(nextA.map(item => item.videoName), ['luma-late.mp4', 'luma-orbit.mp4'])
  assert.deepEqual(
    parseCharacterCreatorHistory(storage.getItem(characterCreatorHistoryKey('cast-b'))).map(item => item.videoName),
    ['brin-orbit.mp4'],
  )

  const attached = attachCharacterCreatorMeshForWorkspace(storage, 'cast-a', 'luma-orbit.mp4', 'luma.glb')
  assert.equal(attached.find(item => item.videoName === 'luma-orbit.mp4')?.hunyuanGlb, 'luma.glb')
  assert.equal(
    parseCharacterCreatorHistory(storage.getItem(characterCreatorHistoryKey('cast-b')))[0]?.hunyuanGlb,
    null,
  )
})

test('Character Creator history remembers sheets and can attach a later mesh', () => {
  const first = rememberCharacterCreatorSheet([], {
    id: 'one',
    name: 'Luma',
    kind: 'character',
    videoName: 'luma-orbit.mp4',
    views: [{ id: 'front', hunyuan: 'front', label: 'Front', filename: 'front.png', url: '/api/v1/file/front.png', time: 0.1 }],
    workspace: 'default',
    createdAt: '2026-08-29T00:00:00Z',
  })
  const second = rememberCharacterCreatorSheet(first, {
    id: 'two',
    name: 'Brin',
    kind: 'character',
    videoName: 'brin-orbit.mp4',
    views: [],
    workspace: 'default',
    createdAt: '2026-08-29T01:00:00Z',
  })
  assert.equal(second[0].name, 'Brin')
  assert.equal(second[1].name, 'Luma')
  const updated = attachCharacterCreatorMesh(second, 'luma-orbit.mp4', 'luma.glb')
  assert.equal(updated.find(item => item.videoName === 'luma-orbit.mp4')?.hunyuanGlb, 'luma.glb')
  const parsed = parseCharacterCreatorHistory(JSON.stringify(updated))
  assert.equal(parsed.length, 2)
  assert.equal(parseCharacterCreatorHistory('not-json').length, 0)
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

test('Character Creator, Runs and collection Workspaces are first-class tabs', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ mediaFilter: 'all', outputSearchQuery: '' })
  try {
    render(<TabFilter />)
    assert.ok(screen.getByRole('tab', { name: /Runs/ }))
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
    assert.ok(screen.getByText(/MiniMax o el LLM interno describen/i))
    assert.ok(screen.getByText(/Turnaround 3D/i))
    assert.ok(screen.getByText(/No es el puppet 2D de Face Rig/i))
    assert.ok(screen.getByRole('button', { name: /Create \/ open CharacterKit Face Rig/ }))
    assert.ok(screen.getByRole('button', { name: /A Prompt opcional/ }))
    assert.ok(screen.getByText(/Turbo nativo desactivado/i))
  assert.ok(screen.getByText(/grabs 2 \/ 21 \/ 42 \/ 63/))
  } finally {
    cleanup()
  }
})
