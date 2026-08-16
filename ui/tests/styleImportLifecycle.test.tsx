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

const attribution = {
  id: 'huggingface:ostris/minimax_h3_1k',
  type: 'huggingface_dataset',
  author: 'ostris',
  name: 'MiniMax H3 - 1K',
  url: 'https://huggingface.co/datasets/ostris/minimax_h3_1k',
  repoId: 'ostris/minimax_h3_1k',
  modelFamily: 'minimax',
  collection: 'MiniMax H3 1K',
  license: null,
  licenseNotice: 'No license specified',
  description: 'Source dataset',
  expectedStyles: 1000,
  expectedBytes: 1_432_969_644,
}

function job(status: 'cancelled' | 'running' | 'cancelling') {
  return {
    jobId: 'style-import-resume',
    status,
    stage: status === 'running' ? 'downloading' : status,
    current: 200,
    total: 1000,
    message: status === 'cancelled'
      ? 'Import cancelled. Partial files were preserved and can be resumed.'
      : status === 'cancelling' ? 'Cancelling safely…' : 'Downloading style media…',
    downloadedBytes: 400_000_000,
    expectedBytes: attribution.expectedBytes,
    resumeAvailable: status === 'cancelled',
    source: attribution,
    preflight: {
      storagePath: '/pinokio/cache/maestro/style-library',
      probePath: '/pinokio/cache',
      downloadedFiles: 400,
      downloadedBytes: 400_000_000,
      expectedBytes: attribution.expectedBytes,
      remainingBytes: 1_032_969_644,
      marginBytes: 536_870_912,
      requiredBytes: 1_569_840_556,
      freeBytes: 50_000_000_000,
      sufficient: true,
    },
  }
}

test('style import exposes durable storage, resume, and cooperative cancel controls', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { StyleSheetPanel } = await import('../src/features/styles/StyleSheetPanel.tsx')
  const originalFetch = globalThis.fetch
  const calls: string[] = []

  globalThis.fetch = async (input, init) => {
    const url = String(input)
    const method = init?.method || 'GET'
    calls.push(`${method} ${url}`)
    if (url.endsWith('/api/v1/style-library/sources')) {
      return Response.json({ sources: [{
        ...attribution,
        installed: false,
        styleCount: 0,
        downloadedFiles: 400,
        downloadedBytes: 400_000_000,
        storagePath: '/pinokio/cache/maestro/style-library',
        latestJob: job('cancelled'),
      }] })
    }
    if (url.includes('/api/v1/style-library/styles?')) {
      return Response.json({ styles: [], total: 0, offset: 0, limit: 60, facets: { sources: [], collections: [], groups: [] } })
    }
    if (url.endsWith('/imports/minimax-h3-1k') && method === 'POST') {
      return Response.json(job('running'))
    }
    if (url.endsWith('/imports/style-import-resume/cancel') && method === 'POST') {
      return Response.json(job('cancelling'))
    }
    throw new Error(`Unexpected request: ${method} ${url}`)
  }

  try {
    render(<StyleSheetPanel />)
    assert.ok(await screen.findByText('Storage: /pinokio/cache/maestro/style-library'))
    assert.ok(screen.getByText('Import cancelled. Partial files were preserved and can be resumed.'))

    fireEvent.click(screen.getByRole('button', { name: 'Reanudar descarga de estilos' }))
    const cancel = await screen.findByRole('button', { name: 'Cancelar' })
    fireEvent.click(cancel)

    await waitFor(() => assert.ok(calls.some(value => value.endsWith('POST /api/v1/style-library/imports/style-import-resume/cancel'))))
    assert.ok(calls.some(value => value.endsWith('POST /api/v1/style-library/imports/minimax-h3-1k')))
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
  }
})
