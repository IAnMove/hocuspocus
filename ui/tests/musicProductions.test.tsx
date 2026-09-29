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
  Event: dom.window.Event,
  Node: dom.window.Node,
  MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { cleanup, fireEvent, render, screen } = await import('@testing-library/react')
const { MusicProductionGrid } = await import('../src/features/music-productions/MusicProductionGrid.tsx')

const manifest = {
  version: 1,
  production_id: 'show',
  title: 'Night bus',
  montage: 'show.montage.json',
  shots: [
    {
      key: 's0',
      kind: 'h3',
      start: 0,
      end: 4,
      sung: true,
      lyric: 'hello night',
      start_frame: 'frame-s0.png',
      clip: 'clip-s0.mp4',
      takes: [{ file: 'take-b.mp4', r: 0.82, verdict: 'ok', take: 2 }],
      scene_doc: 'show-s0.scene.json',
      scene_video: 'show-s0.mp4',
    },
  ],
}

test('music production grid renders a shots.json row and its actions', () => {
  const opened: string[] = []
  const used: string[] = []
  let montage = 0
  render(<MusicProductionGrid
    workspace="film"
    shots={manifest.shots}
    onOpenScene={name => opened.push(name)}
    onRetake={() => undefined}
    onUseTake={(_shot, file) => used.push(file)}
    onOpenMontage={() => { montage += 1 }}
  />)
  assert.equal(screen.getByText('hello night').textContent, 'hello night')
  assert.match(screen.getByText(/take-b\.mp4/).textContent || '', /r 0\.82/)
  assert.match(screen.getByRole('img', { name: 's0' }).getAttribute('src') || '', /frame-s0\.png/)
  fireEvent.click(screen.getByRole('button', { name: 'Open scene' }))
  assert.deepEqual(opened, ['show-s0.scene.json'])
  fireEvent.click(screen.getByRole('button', { name: 'Use this take take-b.mp4' }))
  assert.deepEqual(used, ['take-b.mp4'])
  fireEvent.click(screen.getByRole('button', { name: 'Open montage' }))
  assert.equal(montage, 1)
  cleanup()
})
