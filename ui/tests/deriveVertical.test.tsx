import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  Event: dom.window.Event,
  IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('vertical version button derives 9:16 blur and opens the copy', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { DeriveVerticalButton } = await import('../src/features/video-editor/DeriveVerticalButton.tsx')
  const opened: string[] = []
  render(
    <DeriveVerticalButton
      workspace="x-song"
      file="bird.montage.json"
      onOpened={loaded => { opened.push(loaded.ref.file) }}
      onError={() => { throw new Error('derive failed') }}
      derive={async () => ({ file: 'bird-9-16.montage.json', revision: 1, url: '/file' })}
      load={async () => ({
        state: { projectName: 'Bird (9:16)', resolution: { label: '1080×1920', width: 1080, height: 1920 }, fps: 24, clips: [], soundtrack: null },
        layers: { overlays: [], audioCues: [], duck: 0 },
        ref: { file: 'bird-9-16.montage.json', revision: 1, origins: {} },
      })}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Create vertical version' }))
  await screen.findByRole('button', { name: 'Create vertical version' })
  assert.deepEqual(opened, ['bird-9-16.montage.json'])
  cleanup()
})

test('vertical version button stays hidden without an open montage', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { DeriveVerticalButton } = await import('../src/features/video-editor/DeriveVerticalButton.tsx')
  render(
    <DeriveVerticalButton workspace="x-song" file={null} onOpened={() => undefined} onError={() => undefined} />,
  )
  assert.equal(screen.queryByRole('button', { name: 'Create vertical version' }), null)
  cleanup()
})
