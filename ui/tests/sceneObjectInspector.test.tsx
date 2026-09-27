import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import { applyScene3DTemplate, patchScene3DSlot } from '../src/features/scene3d/templates.ts'
import { defaultSpeech, type FacePlacement } from '../src/features/scene3d/speech/types.ts'
import type { Scene3DDocument } from '../src/features/scene3d/types.ts'
import type { Scene3DSaveState } from '../src/features/scene3d/documentHistory.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React,
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  Event: dom.window.Event,
  KeyboardEvent: dom.window.KeyboardEvent,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const face: FacePlacement = {
  meshIndex: 0,
  center: [0, 1.5, 0.1],
  size: [0.1, 0.08],
  skin: [0.5, 0.3, 0.2],
  eyes: {
    left: [-0.04, 1.55, 0.1],
    right: [0.04, 1.55, 0.1],
    size: [0.04, 0.02],
    skinLeft: [0.5, 0.3, 0.2],
    skinRight: [0.5, 0.3, 0.2],
  },
}

function sampleDocument(): Scene3DDocument {
  const document = applyScene3DTemplate('two-shot')
  document.slots[0].sourceUrl = '/hero.glb'
  document.slots[0].speech = { ...defaultSpeech(), face }
  return document
}

test('inspector edits mouth, GLB, screen and SFX and keeps advanced controls folded', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { SceneObjectInspector } = await import('../src/features/scene3d/SceneObjectInspector.tsx')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n')
  await ensureUiI18n()
  await setUiLanguage('en')
  let current = sampleDocument()
  const view = render(
    <SceneObjectInspector
      document={current}
      selectedId={current.slots[0].id}
      locked={false}
      saveState="unsaved"
      canUndo
      canRedo={false}
      conflict={null}
      preview={<p>Stage preview</p>}
      onChange={next => { current = next }}
      onUndo={() => {}}
      onRedo={() => {}}
      onCheckpoint={() => {}}
      onResolveConflict={() => {}}
    />,
  )
  try {
    assert.equal(screen.getByTestId('scene3d-save-state').textContent, 'Unsaved changes')
    assert.equal((screen.getByTestId('scene3d-inspector-advanced') as HTMLDetailsElement).open, false)
    fireEvent.change(screen.getByTestId('scene3d-inspector-mouth-x'), { target: { value: '0.33' } })
    assert.equal(current.slots[0].speech?.face?.center[0], 0.33)
    fireEvent.change(screen.getByTestId('scene3d-inspector-source'), { target: { value: '/other.glb' } })
    assert.equal(current.slots[0].sourceUrl, '/other.glb')
    fireEvent.click(screen.getByTestId('scene3d-inspector-add-screen'))
    assert.ok(current.slots[0].screen || current.slots.some(slot => slot.media === 'screen'))
    fireEvent.click(screen.getByTestId('scene3d-inspector-add-sfx'))
    assert.ok((current.worldSfx ?? []).length >= 1)
    assert.ok((current.sfx ?? []).length >= 1)
    fireEvent.click(screen.getByTestId('scene3d-inspector-scene'))
    assert.ok(screen.getByTestId('scene3d-inspector-scene-fields'))
    assert.equal((screen.getByTestId('scene3d-inspector-scene-advanced') as HTMLDetailsElement).open, false)
    assert.ok(screen.getByTestId('scene3d-inspector-preview').textContent?.includes('Stage preview'))
    fireEvent.click(screen.getByTestId('scene3d-inspector-preview-toggle'))
    assert.equal(view.queryByTestId('scene3d-inspector-preview'), null)
    await setUiLanguage('es')
    view.rerender(
      <SceneObjectInspector
        document={current}
        selectedId={current.slots[0].id}
        locked={false}
        saveState="unsaved"
        canUndo
        canRedo={false}
        conflict={null}
        onChange={next => { current = next }}
        onUndo={() => {}}
        onRedo={() => {}}
        onCheckpoint={() => {}}
        onResolveConflict={() => {}}
      />,
    )
    assert.equal(screen.getByTestId('scene3d-save-state').textContent, 'Cambios sin guardar')
    assert.ok(screen.getByTestId('scene3d-inspector-object').textContent?.includes('Objeto'))
  } finally {
    cleanup()
    await setUiLanguage('en')
  }
})

test('lock blocks inspector mutations and the conflict choice is explicit', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { SceneObjectInspector } = await import('../src/features/scene3d/SceneObjectInspector.tsx')
  const start = sampleDocument()
  let current = start
  let choice: 'mine' | 'theirs' | undefined
  try {
    const view = render(
      <SceneObjectInspector
        document={current}
        selectedId={current.slots[0].id}
        locked
        saveState="locked"
        canUndo
        canRedo
        conflict={patchScene3DSlot(start, start.slots[0].id, { sourceUrl: '/theirs.glb' })}
        onChange={next => { current = next }}
        onUndo={() => {}}
        onRedo={() => {}}
        onCheckpoint={() => {}}
        onResolveConflict={value => { choice = value }}
      />,
    )
    assert.equal(screen.getByTestId('scene3d-save-state').textContent, 'Locked while exporting')
    fireEvent.change(screen.getByTestId('scene3d-inspector-source'), { target: { value: '/blocked.glb' } })
    assert.equal(current.slots[0].sourceUrl, '/hero.glb')
    fireEvent.click(screen.getByRole('button', { name: 'Keep this tab' }))
    assert.equal(choice, 'mine')
    view.rerender(
      <SceneObjectInspector
        document={current}
        selectedId={current.slots[0].id}
        locked={false}
        saveState="conflict"
        canUndo={false}
        canRedo={false}
        conflict={patchScene3DSlot(start, start.slots[0].id, { sourceUrl: '/theirs.glb' })}
        onChange={next => { current = next }}
        onUndo={() => {}}
        onRedo={() => {}}
        onCheckpoint={() => {}}
        onResolveConflict={value => { choice = value }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Load the other tab' }))
    assert.equal(choice, 'theirs')
  } finally { cleanup() }
})

test('inspector source edits keep image backdrops as image through draft persist', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { SceneObjectInspector } = await import('../src/features/scene3d/SceneObjectInspector.tsx')
  const { persistHistoryDraft, createHistory, readDraftPayload } = await import('../src/features/scene3d/documentHistory.ts')
  const { parseScene3DDocument } = await import('../src/features/scene3d/document.ts')
  const document = applyScene3DTemplate('screen-alert')
  const backdrop = document.slots.find(slot => slot.media === 'image')
  assert.ok(backdrop)
  let current = document
  const memory = new Map<string, string>()
  const storage = {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => { memory.set(key, value) },
    removeItem: (key: string) => { memory.delete(key) },
  }
  try {
    render(
      <SceneObjectInspector
        document={current}
        selectedId={backdrop.id}
        locked={false}
        saveState="unsaved"
        canUndo={false}
        canRedo={false}
        conflict={null}
        onChange={next => { current = next }}
        onUndo={() => {}}
        onRedo={() => {}}
        onCheckpoint={() => {}}
        onResolveConflict={() => {}}
      />,
    )
    fireEvent.change(screen.getByTestId('scene3d-inspector-source'), { target: { value: '/api/v1/uploads/sky.png' } })
    assert.equal(current.slots.find(slot => slot.id === backdrop.id)?.media, 'image')
    assert.equal(current.slots.find(slot => slot.id === backdrop.id)?.sourceUrl, '/api/v1/uploads/sky.png')
    const history = persistHistoryDraft(
      createHistory(current, { workspace: 'promo', documentId: 'alert', revision: 0 }, 'tab'),
      storage,
    )
    const restored = readDraftPayload(storage, history.identity)
    assert.equal(restored?.document.slots.find(slot => slot.id === backdrop.id)?.media, 'image')
    assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(current)))?.slots.find(slot => slot.id === backdrop.id)?.media, 'image')
  } finally { cleanup() }
})

test('inspector history buttons drive undo and checkpoint', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { SceneObjectInspector } = await import('../src/features/scene3d/SceneObjectInspector.tsx')
  let undo = 0
  let redo = 0
  let checkpoint = 0
  try {
    render(
      <SceneObjectInspector
        document={sampleDocument()}
        selectedId="subject_1"
        locked={false}
        saveState="saved"
        canUndo
        canRedo
        conflict={null}
        onChange={() => {}}
        onUndo={() => { undo += 1 }}
        onRedo={() => { redo += 1 }}
        onCheckpoint={() => { checkpoint += 1 }}
        onResolveConflict={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('scene3d-history-undo'))
    fireEvent.click(screen.getByTestId('scene3d-history-redo'))
    fireEvent.click(screen.getByTestId('scene3d-history-checkpoint'))
    assert.deepEqual({ undo, redo, checkpoint }, { undo: 1, redo: 1, checkpoint: 1 })
    assert.equal(screen.getByTestId('scene3d-save-state').textContent, 'Saved')
  } finally { cleanup() }
})

test('a host can round-trip inspector edits through document history', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { SceneObjectInspector } = await import('../src/features/scene3d/SceneObjectInspector.tsx')
  const {
    applyHistoryChange, createHistory, undoHistory, redoHistory, historySaveState,
  } = await import('../src/features/scene3d/documentHistory.ts')
  const start = sampleDocument()
  function Host() {
    const [history, setHistory] = useState(() => createHistory(start, { workspace: 'ws', documentId: 'live', revision: 0 }, 'tab'))
    const saveState = historySaveState(history) as Scene3DSaveState
    return (
      <SceneObjectInspector
        document={history.present}
        selectedId={history.present.slots[0].id}
        locked={history.locked}
        saveState={saveState}
        canUndo={history.past.length > 0}
        canRedo={history.future.length > 0}
        conflict={history.conflict}
        onChange={(next, group) => setHistory(current => applyHistoryChange(current, next, group))}
        onUndo={() => setHistory(current => undoHistory(current))}
        onRedo={() => setHistory(current => redoHistory(current))}
        onCheckpoint={() => {}}
        onResolveConflict={() => {}}
      />
    )
  }
  try {
    render(<Host />)
    fireEvent.change(screen.getByTestId('scene3d-inspector-mouth-x'), { target: { value: '0.5' } })
    fireEvent.change(screen.getByTestId('scene3d-inspector-source'), { target: { value: '/swapped.glb' } })
    fireEvent.click(screen.getByTestId('scene3d-inspector-add-screen'))
    fireEvent.click(screen.getByTestId('scene3d-inspector-add-sfx'))
    fireEvent.click(screen.getByTestId('scene3d-history-undo'))
    fireEvent.click(screen.getByTestId('scene3d-history-undo'))
    fireEvent.click(screen.getByTestId('scene3d-history-undo'))
    fireEvent.click(screen.getByTestId('scene3d-history-undo'))
    assert.equal((screen.getByTestId('scene3d-inspector-source') as HTMLInputElement).value, '/hero.glb')
    assert.equal((screen.getByTestId('scene3d-inspector-mouth-x') as HTMLInputElement).value, '0')
    fireEvent.click(screen.getByTestId('scene3d-history-redo'))
    fireEvent.click(screen.getByTestId('scene3d-history-redo'))
    fireEvent.click(screen.getByTestId('scene3d-history-redo'))
    fireEvent.click(screen.getByTestId('scene3d-history-redo'))
    assert.equal((screen.getByTestId('scene3d-inspector-source') as HTMLInputElement).value, '/swapped.glb')
    assert.equal((screen.getByTestId('scene3d-inspector-mouth-x') as HTMLInputElement).value, '0.5')
  } finally { cleanup() }
})
