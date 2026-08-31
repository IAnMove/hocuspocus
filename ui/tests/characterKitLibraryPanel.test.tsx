import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit, emptyCharacterKitLibrary } from '../src/lib/characterKit.ts'

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
}

installDom()

test('Character Kits explain the next click instead of library jargon', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { CharacterKitLibraryPanel } = await import('../src/features/characters/CharacterKitLibraryPanel.tsx')
  const kit = {
    ...createCharacterKit('Brin'),
    base: {
      id: 'brin-base',
      name: 'Brin',
      source: '/api/v1/file/brin-cutout-base-v1.png',
      kind: 'image' as const,
      alphaStatus: 'transparent' as const,
      reviewState: 'approved' as const,
    },
    poses: {
      reaction: {
        id: 'brin-reaction',
        name: 'reaction',
        source: '/api/v1/file/brin-cutout-reaction-v1.png',
        kind: 'image' as const,
        alphaStatus: 'transparent' as const,
        reviewState: 'approved' as const,
      },
    },
    mouth: {
      closed: {
        id: 'closed',
        name: 'closed',
        source: '/api/v1/file/brin-mouth-closed-v1.png',
        kind: 'overlay' as const,
        alphaStatus: 'transparent' as const,
        reviewState: 'approved' as const,
      },
      wide: {
        id: 'wide',
        name: 'wide',
        source: '/api/v1/file/brin-mouth-wide-v1.png',
        kind: 'overlay' as const,
        alphaStatus: 'transparent' as const,
        reviewState: 'approved' as const,
      },
    },
  }
  const library = { ...emptyCharacterKitLibrary(), revision: 10, activeId: kit.id, kits: { [kit.id]: kit } }
  const noop = () => undefined
  try {
    render(
      <CharacterKitLibraryPanel
        library={library}
        draft={kit}
        poseId="reaction"
        tab="kit"
        busy={false}
        error={null}
        newName=""
        alphaStatus="transparent"
        mouthState="wide"
        hasSelectedLayer={false}
        selectedIsFace={false}
        onSelectKit={noop}
        onNewNameChange={noop}
        onCreateFromSelected={noop}
        onDraftChange={noop}
        onPoseIdChange={noop}
        onTabChange={noop}
        onAlphaStatusChange={noop}
        onMouthStateChange={noop}
        onAssignSelected={noop}
        onCaptureAnchor={noop}
        onSave={noop}
        onPutOnScene={noop}
        onDelete={noop}
        onClose={noop}
      />,
    )
    assert.ok(screen.getByText('Personajes recortables'))
    assert.ok(screen.getByText(/Un personaje es un cuerpo/))
    assert.ok(screen.getByText(/Coloca la caja sobre los labios/))
    assert.ok(screen.getByRole('button', { name: 'Poner en la escena' }))
    assert.ok(screen.getByRole('button', { name: 'Guardar' }))
    assert.ok(screen.getByRole('button', { name: /Ir a Bocas y ojos/ }))
    assert.ok(screen.getByText('Reacción'))
    assert.equal(screen.queryByText(/Workspace library/i), null)
    assert.equal(screen.queryByText(/Keep one reviewed identity/i), null)
    assert.equal(screen.queryByText(/Pose id/i), null)
    assert.equal(screen.queryByText(/Selected → base/i), null)
  } finally {
    cleanup()
  }
})
