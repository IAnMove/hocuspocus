import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class {
    observe() {}
    disconnect() {}
  },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const capabilities = {
  runtime: { installed: true, isolated_runtime: true, releases_vram_after_job: true, install_hint: null },
  models: [{
    id: 'hunyuan3d-2-turbo', label: 'Hunyuan3D 2 Turbo', engine: 'v2', repo: 'Tencent/Hunyuan3D-2',
    subfolder: 'turbo', parameters: '1.1B', multiview: false, turbo: true, supports_text: true,
    recommended_vram_gb: 6, description: 'Fast single-view reconstruction',
  }],
  presets: [{
    id: 'balanced', label: 'Balanced', description: 'Balanced quality', model_id: 'hunyuan3d-2-turbo',
    num_inference_steps: 5, guidance_scale: 5, octree_resolution: 256, num_chunks: 12000,
    texture_mode: 'v2-turbo', cpu_offload: true, flashvdm: true,
  }],
  texture_modes: [{ id: 'v2-turbo', label: 'Turbo texture', recommended_vram_gb: 6 }],
  input_views: ['front', 'left', 'right', 'back'],
  output_formats: ['glb'],
  active_jobs: 0,
}

test('Hunyuan3D keeps disk upload and can use a Loreframe image in the active workspace', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Hunyuan3DPanel } = await import('../src/components/Sidebar/Hunyuan3DPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  let submitted: Record<string, unknown> | null = null
  useStore.setState(state => ({
    activeWorkspace: 'gallery-workspace',
    params: { ...state.params, model_type: 'hunyuan3d-2-turbo', prompt: '' },
    enabledModels: new Set<string>(),
    maybeRefreshGallery: async () => undefined,
  }))
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/model3d/capabilities')) {
      return new Response(JSON.stringify(capabilities), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/outputs')) {
      return new Response(JSON.stringify({
        outputs: [{
          name: 'bronze_robot_reference.png', type: 'image', mode: 'image', size: 42, created_at: 1,
          url: '/api/v1/file/bronze_robot_reference.png?workspace=gallery-workspace',
          thumbnail_url: '/api/v1/outputs/thumbnail/bronze_robot_reference.png?workspace=gallery-workspace',
        }],
        total: 1,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/model3d/generate') && init?.method === 'POST') {
      submitted = JSON.parse(String(init.body || '{}'))
      return new Response(JSON.stringify({
        job_id: 'model3d-gallery-test', status: 'completed', progress: 1, phase: 'completed',
        message: 'Ready', error: null, filename: 'robot.glb', url: '/api/v1/file/robot.glb',
        model_id: 'hunyuan3d-2-turbo',
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/model-visibility')) {
      return new Response('{}', { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch

  try {
    render(<Hunyuan3DPanel />)
    await screen.findByRole('button', { name: 'Choose Front image from Loreframe' })
    assert.ok(screen.getByRole('button', { name: 'Upload Front image from disk' }))

    fireEvent.click(screen.getByRole('button', { name: 'Choose Front image from Loreframe' }))
    await screen.findByRole('listbox', { name: 'Loreframe images for Front view' })
    fireEvent.click(screen.getByRole('option', { name: 'bronze_robot_reference.png' }))
    assert.ok(screen.getByText('bronze_robot_reference.png'))

    const generate = screen.getByRole('button', { name: 'Generate 3D asset' }) as HTMLButtonElement
    assert.equal(generate.disabled, false)
    fireEvent.click(generate)
    await waitFor(() => assert.ok(submitted))
    assert.deepEqual(submitted?.images, { front: 'bronze_robot_reference.png' })
    assert.equal(submitted?.workspace, 'gallery-workspace')
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})
