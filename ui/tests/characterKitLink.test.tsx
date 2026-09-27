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
    HTMLSelectElement: dom.window.HTMLSelectElement,
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

test('Story/Series character link lists 2D kits; 3D talker link can hide them', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { CharacterKitLink } = await import('../src/features/characters/CharacterKitLink.tsx')
  const paper = {
    ...createCharacterKit('Nilo Carda'),
    id: 'nilo',
    base: {
      id: 'nilo-body',
      name: 'body',
      source: '/examples/cut-paper/puppets/nilo-body.png',
      kind: 'image' as const,
      alphaStatus: 'transparent' as const,
      reviewState: 'approved' as const,
    },
  }
  const talker = {
    ...createCharacterKit('Alice'),
    id: 'alice',
    speech3d: {
      digest: 'a'.repeat(64),
      model: { workspaceId: 'default', filename: 'alice.glb', url: '/api/v1/file/alice.glb' },
    },
  }
  const kits = Object.values({ ...emptyCharacterKitLibrary(), kits: { nilo: paper, alice: talker } }.kits)
  try {
    const { rerender } = render(
      <CharacterKitLink workspace="default" kits={kits} value={undefined} onChange={() => undefined} />,
    )
    const select = screen.getByTestId('character-kit-link') as HTMLSelectElement
    const labels = [...select.options].map(option => option.textContent)
    assert.ok(labels.some(label => label?.includes('Nilo Carda') && label.includes('2D')))
    assert.ok(labels.some(label => label?.includes('Alice') && label.includes('3D')))
    rerender(
      <CharacterKitLink workspace="default" requireSpeech3d kits={kits} value={undefined} onChange={() => undefined} />,
    )
    const talkerLabels = [...(screen.getByTestId('character-kit-link') as HTMLSelectElement).options].map(option => option.textContent)
    assert.equal(talkerLabels.some(label => label?.includes('Nilo')), false)
    assert.ok(talkerLabels.some(label => label?.includes('Alice')))
    rerender(
      <CharacterKitLink workspace="default" kits={[]} error="Could not load Character Kits" value={undefined} onChange={() => undefined} />,
    )
    assert.equal(screen.getByRole('status').textContent, 'Could not load Character Kits')
  } finally {
    cleanup()
  }
})
