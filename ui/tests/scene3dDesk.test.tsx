import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { Object3D } from 'three'
import { addPickerCatalog } from '../src/features/scene3d/addPickerCatalog'
import { applyAddPicker } from '../src/features/scene3d/pickerApply'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { transformPatch } from '../src/features/scene3d/transformGizmo'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import type { Scene3DDeskModel } from '../src/features/scene3d/scene3dDeskModel'
import type { Scene3DDocument } from '../src/features/scene3d/types.ts'

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
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

function item(id: string) {
  const found = addPickerCatalog().find(entry => entry.id === id)
  assert.ok(found, id)
  return found
}

test('picking an effect or a text template changes the document and a demo does not', () => {
  const document = createDefaultScene3DDocument()
  const world = applyAddPicker(document, item('world:phoenix'))
  assert.equal(world?.worldSfx?.[0]?.kind, 'phoenix')
  const overlayId = addPickerCatalog().find(entry => entry.category === 'overlay')?.id
  assert.ok(overlayId)
  const overlay = applyAddPicker(document, item(overlayId))
  assert.ok((overlay?.sfx ?? []).length > 0)
  const textId = addPickerCatalog().find(entry => entry.category === 'text')?.id
  assert.ok(textId)
  const texts = applyAddPicker(document, item(textId))
  assert.ok((texts?.texts ?? []).length > 0)
  assert.equal(applyAddPicker(document, item('world-demo:depth')), null)
  assert.equal(applyAddPicker(document, item('showcase:all')), null)
})

test('select mode writes no transform', () => {
  const proxy = new Object3D()
  proxy.position.set(1, 2, 3)
  proxy.rotation.set(0.2, 0.4, 0.6)
  assert.deepEqual(transformPatch(proxy, 'select', null), {})
  assert.deepEqual(transformPatch(proxy, 'translate', null).position, [1, 2, 3])
})

test('document controls show only the section the desk asked for', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { Scene3DDocumentControls } = await import('../src/features/scene3d/Scene3DDocumentControls')
  const document = createDefaultScene3DDocument()
  const props = {
    document,
    disabled: false,
    workspace: 'demo',
    preview: () => undefined,
    onChange: () => undefined,
    onLoad: () => undefined,
  }
  try {
    const files = render(<Scene3DDocumentControls {...props} section="files" />)
    assert.ok(screen.getByRole('button', { name: 'Save shot JSON' }))
    assert.equal(screen.queryByRole('button', { name: 'Save scene to gallery' }), null)
    files.unmount()
    const library = render(<Scene3DDocumentControls {...props} section="library" />)
    assert.ok(screen.getByRole('button', { name: 'Save scene to gallery' }))
    assert.ok(screen.getByLabelText('Scene name'))
    assert.equal(screen.queryByTestId('world3d-frame-tier'), null)
    library.unmount()
    render(<Scene3DDocumentControls {...props} section="timing" />)
    assert.ok(screen.getByTestId('world3d-frame-tier'))
    assert.equal(screen.queryByRole('button', { name: 'Save shot JSON' }), null)
  } finally {
    cleanup()
  }
})

test('the desk inspector hides the duplicate pose and the history bar', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { SceneObjectInspector } = await import('../src/features/scene3d/SceneObjectInspector.tsx')
  const document: Scene3DDocument = applyScene3DTemplate('two-shot')
  try {
    render(
      <SceneObjectInspector
        document={document}
        selectedId={document.slots[0].id}
        locked={false}
        saveState="saved"
        canUndo={false}
        canRedo={false}
        conflict={null}
        showHistory={false}
        showPreview={false}
        showPose={false}
        onChange={() => undefined}
        onUndo={() => undefined}
        onRedo={() => undefined}
        onCheckpoint={() => undefined}
        onResolveConflict={() => undefined}
      />,
    )
    assert.equal(screen.queryByText('Inspector position'), null)
    assert.ok(screen.getByTestId('scene3d-inspector-source'))
    assert.equal(screen.queryByTestId('scene3d-history-undo'), null)
  } finally {
    cleanup()
  }
})

test('the desk bar keeps one row by moving expand, then history, into More', async () => {
  const { deskBarOverflow } = await import('../src/features/scene3d/deskBar')
  assert.deepEqual(deskBarOverflow(1400), [])
  assert.deepEqual(deskBarOverflow(860), ['expand'])
  assert.deepEqual(deskBarOverflow(640), ['expand', 'history'])
})

test('save is a split button whose menu marks the scene saved', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DLibraryControls } = await import('../src/features/scene3d/Scene3DLibraryControls')
  const document = createDefaultScene3DDocument()
  let marked = 0
  try {
    render(
      <Scene3DLibraryControls
        document={document}
        workspace="demo"
        disabled={false}
        preview={() => undefined}
        onLoad={() => undefined}
        onCheckpoint={() => { marked += 1 }}
        checkpointLabel="Mark saved"
      />,
    )
    assert.equal(screen.getByRole('button', { name: 'Save scene to gallery' }).textContent, 'Save')
    assert.equal(screen.getByRole('button', { name: 'Open scene' }).textContent, 'Open')
    fireEvent.click(screen.getByTestId('scene3d-save-menu'))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Mark saved' }))
    assert.equal(marked, 1)
  } finally {
    cleanup()
  }
})

test('the outline puts the scene in the list and adds from one menu', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DDeskOutline } = await import('../src/features/scene3d/Scene3DDeskOutline')
  const document = createDefaultScene3DDocument()
  const picks: string[] = []
  const selected: string[] = []
  const model = {
    editingLocked: false,
    exporting: false,
    sceneDoc: document,
    selectedId: '',
    selected: undefined,
    keepAssets: true,
    workspace: 'demo',
    preview: () => undefined,
    selectSlot: (id: string) => selected.push(id),
    openPicker: (category: string) => picks.push(category),
    addScreen: () => picks.push('screen'),
    removeSelected: () => undefined,
    setKeepAssets: () => undefined,
    mountTemplate: () => undefined,
    mountUserTemplate: () => undefined,
  } as unknown as Scene3DDeskModel
  try {
    render(<Scene3DDeskOutline model={model} />)
    const scene = screen.getByTestId('scene3d-desk-scene')
    assert.equal(scene.getAttribute('aria-pressed'), 'true')
    assert.equal(screen.getByTestId('scene3d-object-list').contains(scene), true)
    fireEvent.click(scene)
    assert.deepEqual(selected, [''])
    fireEvent.click(screen.getByTestId('scene3d-desk-add'))
    fireEvent.click(screen.getByRole('menuitem', { name: 'New object' }))
    fireEvent.click(screen.getByTestId('scene3d-desk-add'))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Add screen' }))
    fireEvent.click(screen.getByTestId('scene3d-desk-add'))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Effect or prop…' }))
    assert.deepEqual(picks, ['prop', 'screen', 'all'])
    const card = screen.getByTestId('world3d-shot-card')
    assert.match(card.className, /grid-cols-/)
    assert.equal(card.contains(screen.getByTestId('world3d-open-library')), true)
  } finally {
    cleanup()
  }
})

test('the viewport toolbar has one Move button and a Select tool', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DViewportTools } = await import('../src/features/scene3d/Scene3DViewportTools')
  const seen: string[] = []
  try {
    render(<Scene3DViewportTools mode="translate" disabled={false} onMode={mode => seen.push(mode)} caption="3D stage · Shot" captionNote="Editor preview" />)
    const move = screen.getByRole('button', { name: 'Move' })
    assert.equal(move.getAttribute('aria-pressed'), 'true')
    assert.equal(screen.getByRole('button', { name: 'Rotate', exact: true }).textContent, 'Rotate')
    const bar = screen.getByTestId('scene3d-viewport-tools')
    assert.match(bar.className, /\bz-10\b/)
    assert.equal(/z-\[930\]/.test(bar.className), false)
    assert.equal(bar.textContent?.includes('3D stage · Shot'), true)
    assert.equal(bar.textContent?.includes('Editor preview'), true)
    fireEvent.click(screen.getByRole('button', { name: 'Select' }))
    assert.deepEqual(seen, ['select'])
  } finally {
    cleanup()
  }
})

test('the prop category of the picker shows the prop library slot', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { Scene3DAddPicker } = await import('../src/features/scene3d/Scene3DAddPicker')
  try {
    render(
      <Scene3DAddPicker
        open
        initialCategory="prop"
        onPick={() => undefined}
        onClose={() => undefined}
        props={<p data-testid="prop-mark">props</p>}
      />,
    )
    assert.ok(screen.getByTestId('prop-mark'))
    assert.equal(screen.queryByTestId('scene3d-add-item-world:phoenix'), null)
  } finally {
    cleanup()
  }
})
