import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLOptionElement: dom.window.HTMLOptionElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { cleanup, fireEvent, render, screen } = await import('@testing-library/react')
const { formatPublishNumber, publishMediaSource } = await import('../src/api/publish')
const { PublishPresetBar } = await import('../src/features/video-editor/PublishPresetBar')

afterEach(() => cleanup())

const props = {
  width: 1920,
  height: 1080,
  duration: 8,
  overlays: [],
  source: 'clip.mp4',
  workspace: 'demo',
  onError: () => undefined,
  check: async () => [],
}

test('the publish bar names each platform target and shows the measured loudness', async () => {
  const publish = async () => ({
    file: 'clip_apple.mp4',
    url: '/api/v1/file/clip_apple.mp4',
    thumbnail: 'clip_apple.png',
    sidecar: 'clip_apple.publish.json',
    warnings: [],
    loudness: { lufs: -16.0, true_peak: -1.4, target_lufs: -16, target_true_peak: -1 },
  })
  render(<PublishPresetBar {...props} publish={publish} />)
  assert.ok(screen.getByRole('option', { name: 'YouTube · −14 LUFS' }))
  assert.ok(screen.getByRole('option', { name: 'Apple · −16 LUFS' }))
  assert.ok(screen.getByRole('option', { name: 'Broadcast · −23 LUFS' }))
  assert.ok(screen.getByRole('option', { name: 'Archive master' }))
  fireEvent.change(screen.getByLabelText('Publish preset'), { target: { value: 'apple' } })
  fireEvent.click(screen.getByRole('button', { name: 'Publish' }))
  assert.ok(await screen.findByText('-16.0 LUFS · -1.4 dBTP'))
})

test('measured loudness survives a missing true peak', async () => {
  assert.equal(formatPublishNumber(-16), '-16.0')
  assert.equal(formatPublishNumber(null), '—')
  assert.equal(formatPublishNumber(Number.NEGATIVE_INFINITY), '—')

  const publish = async () => ({
    file: 'clip_youtube.mp4',
    url: '/api/v1/file/clip_youtube.mp4',
    thumbnail: 'clip_youtube.png',
    sidecar: 'clip_youtube.publish.json',
    warnings: [{ code: 'loudness' as const, lufs: -70, target_lufs: -14 }],
    loudness: { lufs: -70, true_peak: null, target_lufs: -14, target_true_peak: -1 },
  })
  render(<PublishPresetBar {...props} publish={publish} />)
  fireEvent.click(screen.getByRole('button', { name: 'Publish' }))
  assert.ok(await screen.findByText('-70.0 LUFS · — dBTP'))
})

test('publish attaches the workspace to an export file URL', async () => {
  assert.equal(publishMediaSource('/api/v1/file/clip.mp4', 'demo'), '/api/v1/file/clip.mp4?workspace=demo')
  assert.equal(publishMediaSource('/api/v1/file/clip.mp4?workspace=demo', 'demo'), '/api/v1/file/clip.mp4?workspace=demo')
  assert.equal(publishMediaSource('clip.mp4', 'demo'), 'clip.mp4')

  let sent = ''
  const publish = async (payload: { source: string }) => {
    sent = payload.source
    return {
      file: 'clip_x.mp4',
      url: '/api/v1/file/clip_x.mp4',
      thumbnail: 'clip_x.png',
      sidecar: 'clip_x.publish.json',
      warnings: [],
      loudness: { lufs: -14.0, true_peak: -1.0 },
    }
  }
  render(<PublishPresetBar {...props} source="/api/v1/file/clip.mp4" publish={publish} />)
  fireEvent.click(screen.getByRole('button', { name: 'Publish' }))
  assert.ok(await screen.findByText('-14.0 LUFS · -1.0 dBTP'))
  assert.equal(sent, '/api/v1/file/clip.mp4?workspace=demo')
})
