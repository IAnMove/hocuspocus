import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { applyScene3DTemplate } from '../src/features/scene3d/templates'
import type { MotionLabSettings } from '../src/features/scene3d/motionlab/types'
const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, HTMLInputElement: dom.window.HTMLInputElement, MutationObserver: dom.window.MutationObserver, getComputedStyle: dom.window.getComputedStyle })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
test('editor native controls patch the same serializable settings used by MCP and respect locking', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { MotionLabControls } = await import('../src/features/scene3d/motionlab/controls')
  const document = applyScene3DTemplate('motion-bouncing-ball')
  let patch: MotionLabSettings | undefined
  try {
    const view = render(<MotionLabControls document={document} disabled={false} onChange={value => { patch = value }} />)
    fireEvent.change(screen.getByLabelText('Tempo (BPM)'), { target: { value: '96' } })
    assert.equal(patch?.bpm, 96); assert.equal(patch?.color, document.motionLab?.color)
    view.rerender(<MotionLabControls document={document} disabled={true} onChange={() => {}} />)
    assert.ok((screen.getByTestId('motion-lab-controls') as HTMLFieldSetElement).disabled)
    view.rerender(<MotionLabControls document={applyScene3DTemplate('two-shot')} disabled={false} onChange={() => {}} />)
    assert.equal(screen.queryByTestId('motion-lab-controls'), null)
  } finally { cleanup() }
})
