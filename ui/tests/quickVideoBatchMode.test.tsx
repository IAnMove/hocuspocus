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
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('Quick Video batch falls back from missing references to image-guided mode', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const { QuickVideoBatchPanel } = await import('../src/features/stories/QuickVideoBatchPanel.tsx')
  const originalFetch = globalThis.fetch
  const payloads: Array<Record<string, unknown>> = []
  const project = createStoryProject('quick_video')
  project.musicVideoGenerationMode = 'direct_references'

  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url.includes('/quick-video-batches?')) return Response.json({ jobs: [] })
    if (url.endsWith('/quick-video-batches/start') && init?.method === 'POST') {
      payloads.push(JSON.parse(String(init.body)))
      return Response.json({
        jobId: 'quick-batch-test', taskId: 'task-quick-batch-test', workspace: 'default',
        title: 'Test batch', status: 'queued', stage: 'queued', current: 0, total: 1,
        message: 'Queued', error: null, continueOnError: true, settings: {}, items: [],
        createdAt: 1, updatedAt: 1, finishedAt: null,
      })
    }
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${url}`)
  }

  try {
    render(<QuickVideoBatchPanel
      project={project}
      workspace="default"
      videoModel="minimax_h3_legacy"
      imageModel="flux2_klein_9b"
      resolution="540p"
      aspectRatio="9:16"
      durationSeconds={15}
    />)
    const imageGuided = screen.getByRole('button', { name: /Imagen inicial/ })
    const references = screen.getByRole('button', { name: /Referencias/ })
    assert.equal(imageGuided.getAttribute('aria-pressed'), 'true')
    assert.equal(references.getAttribute('aria-pressed'), 'false')

    fireEvent.change(screen.getByLabelText('Ideas para lote de vídeos rápidos, una por línea'), {
      target: { value: 'Un robot pierde su sombra' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Encolar 1 vídeo' }))
    await waitFor(() => assert.equal(payloads.length, 1))
    const settings = payloads[0].settings as Record<string, unknown>
    assert.equal(settings.generationMode, 'image_guided')
    assert.deepEqual(settings.references, [])

    fireEvent.click(screen.getByRole('button', { name: /Texto a vídeo/ }))
    assert.ok(screen.getByText('Cada línea definirá su propio estilo visual; no se aplicará una hoja de estilo global.'))
    fireEvent.change(screen.getByLabelText('Ideas para lote de vídeos rápidos, una por línea'), {
      target: { value: 'Stop-motion: una criatura abre una puerta imposible' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Encolar 1 vídeo' }))
    await waitFor(() => assert.equal(payloads.length, 2))
    const directSettings = payloads[1].settings as Record<string, unknown>
    assert.equal(directSettings.generationMode, 'direct_video')
    assert.match(String(directSettings.directVideoMasterPrompt), /Each batch idea defines its own visual style/)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
  }
})
