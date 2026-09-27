import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { createUserTemplate } from '../src/features/scene3d/userTemplates.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement,
  File: dom.window.File, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test.afterEach(() => { window.localStorage.clear() })

function jsonFile(name: string, value: unknown) {
  const body = JSON.stringify(value)
  const file = new File([body], name, { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => body })
  return file
}

test('My scenarios exports, applies, imports and removes a pack', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DUserTemplates } = await import('../src/features/scene3d/Scene3DUserTemplates')
  const scene = applyScene3DTemplate('cafe-dance')
  const applied: string[] = []
  URL.createObjectURL = () => 'blob:download'
  URL.revokeObjectURL = () => {}
  window.HTMLAnchorElement.prototype.click = () => {}
  try {
    render(<Scene3DUserTemplates document={scene} disabled={false} onApply={pack => { applied.push(pack.id) }} />)
    assert.match(screen.getByText(/No imported scenarios/).textContent || '', /Export/)
    fireEvent.change(screen.getByLabelText('Scenario name'), { target: { value: 'Harbor cafe' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export scenario template' }))
    fireEvent.click(screen.getByRole('button', { name: 'Harbor cafe' }))
    assert.equal(applied.length, 1)
    assert.match(applied[0], /^user-/)
    const pack = createUserTemplate({ document: scene, title: 'Imported dock', id: 'user-dock' })
    fireEvent.change(screen.getByLabelText('Scenario template JSON file'), {
      target: { files: [jsonFile('dock.world3d.template.json', pack)] },
    })
    await waitFor(() => screen.getByRole('button', { name: 'Imported dock' }))
    fireEvent.click(screen.getByTestId('world3d-user-template-user-dock'))
    assert.equal(applied.at(-1), 'user-dock')
    fireEvent.click(screen.getByRole('button', { name: 'Remove Imported dock' }))
    assert.equal(screen.queryByRole('button', { name: 'Imported dock' }), null)
  } finally { cleanup() }
})

test('opening a scenario template as shot JSON points to My scenarios', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DDocumentControls } = await import('../src/features/scene3d/Scene3DDocumentControls')
  const pack = createUserTemplate({ document: createDefaultScene3DDocument(), title: 'Dock', id: 'user-dock' })
  let loaded = 0
  try {
    render(<Scene3DDocumentControls document={createDefaultScene3DDocument()} disabled={false} workspace="demo"
      preview={() => undefined} onChange={() => {}} onLoad={() => { loaded++ }} />)
    fireEvent.change(screen.getByLabelText('Open shot JSON'), {
      target: { files: [jsonFile('dock.world3d.template.json', pack)] },
    })
    await waitFor(() => assert.match(screen.getByRole('alert').textContent || '', /My scenarios/))
    assert.equal(loaded, 0)
  } finally { cleanup() }
})
