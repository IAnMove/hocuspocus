import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html lang="en"><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLImageElement: dom.window.HTMLImageElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  HTMLVideoElement: dom.window.HTMLVideoElement,
  KeyboardEvent: dom.window.KeyboardEvent,
  Event: dom.window.Event,
  Node: dom.window.Node,
  MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { cleanup, fireEvent, render, screen } = await import('@testing-library/react')
const { ReviewMode } = await import('../src/features/music-productions/ReviewMode.tsx')

const shots = [
  {
    key: 's0',
    lyric: 'hello night',
    frame_prompt: 'a face',
    action: 'sings',
    scene_doc: 'show-s0.scene.json',
    scene_video: 'show-s0.mp4',
    takes: [{ file: 'take-b.mp4', r: 0.82 }],
    review: { status: 'pending' as const, locked: false, history_id: 'h1' },
  },
  {
    key: 's1',
    lyric: 'cold street',
    scene_doc: 'show-s1.scene.json',
    scene_video: 'show-s1.mp4',
    review: { status: 'approved' as const, locked: true },
  },
]

test('review mode approves, navigates, filters, and applies a shown diff', () => {
  const approved: string[] = []
  const opened: string[] = []
  const undone: string[] = []
  const used: string[] = []
  let applied = ''
  render(<ReviewMode
    workspace="film"
    shots={shots}
    onClose={() => undefined}
    onApprove={shot => approved.push(shot)}
    onRequest={() => ({
      plan: { summary: 'warmer light', changes: [{ op: 'note' }] },
      diff: [{ op: 'note', shot: 's0', text: 'warmer' }],
      cost_estimate: { image_jobs: 0, clip_jobs: 0, scene_exports: 0, tokens: null },
    })}
    onApply={(shot, _instruction, shown) => { applied = `${shot}:${shown.plan?.summary}` }}
    onOpenScene={name => opened.push(name)}
    onUseTake={(_shot, file) => used.push(file)}
    onUndo={shot => undone.push(shot)}
    onLock={() => undefined}
  />)
  assert.equal(screen.getByText('1/2 approved').textContent, '1/2 approved')
  assert.match(screen.getByLabelText('Scene video').getAttribute('src') || '', /show-s0\.mp4/)
  const dialog = screen.getByRole('dialog')
  fireEvent.keyDown(dialog, { key: 'Enter' })
  assert.deepEqual(approved, ['s0'])
  fireEvent.keyDown(dialog, { key: 'j' })
  assert.equal(screen.getByRole('heading', { name: 's1' }).textContent, 's1')
  fireEvent.keyDown(dialog, { key: 'ArrowLeft' })
  assert.equal(screen.getByRole('heading', { name: 's0' }).textContent, 's0')
  const filter = screen.getByRole('button', { name: 'Pending only' })
  fireEvent.click(filter)
  assert.equal(filter.getAttribute('aria-pressed'), 'true')
  assert.equal(screen.queryByRole('heading', { name: 's1' }), null)
  const note = screen.getByRole('textbox', { name: 'What should change' })
  fireEvent.change(note, { target: { value: 'make it warmer' } })
  fireEvent.keyDown(note, { key: 'Enter' })
  assert.deepEqual(approved, ['s0'])
  fireEvent.click(screen.getByRole('button', { name: 'Request change' }))
  assert.equal(screen.getByText('warmer light').textContent, 'warmer light')
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Enter' })
  assert.deepEqual(approved, ['s0'])
  fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
  assert.equal(applied, 's0:warmer light')
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  assert.deepEqual(undone, ['s0'])
  fireEvent.click(screen.getByRole('button', { name: 'Open scene' }))
  assert.deepEqual(opened, ['show-s0.scene.json'])
  fireEvent.click(screen.getByRole('button', { name: 'Use this take take-b.mp4' }))
  assert.deepEqual(used, ['take-b.mp4'])
  assert.equal(screen.getByRole('button', { name: 'Lock' }).getAttribute('type'), 'button')
  cleanup()
})
