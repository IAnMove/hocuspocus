import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLImageElement: dom.window.HTMLImageElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('Tools exposes exact library images for background removal', async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { ToolsPanel } = await import('../src/components/Sidebar/ToolsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  globalThis.fetch = async input => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({
        total: 1,
        assets: [{
          id: 'asset-hero', kind: 'image', filename: 'hero.png', size_bytes: 12,
          created_at: 1, completed_at: 2, metadata_status: 'canonical', workspace_ids: ['default'],
          locations: [{ workspace_id: 'default', filename: 'hero.png', url: '/api/v1/file/hero.png?workspace=default' }],
          url: '/api/v1/file/hero.png?workspace=default',
          origin: { tool: 'studio' }, execution: {}, model: { provider: 'local', id: 'flux' },
          prompt_preview: 'hero',
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${requestUrl}`)
  }
  useStore.setState({
    toolsTool: 'remove_background', toolsSourcePath: null, toolsSourceName: null,
    toolsSourceUrl: null, toolsSourceAssetId: null, toolsSourceWorkspace: null, toolsSourceKind: null,
    toolsSubmitting: false,
    activeWorkspace: 'default', outputs: [], selectedOutput: -1,
  } as never)
  try {
    render(<ToolsPanel />)
    await waitFor(() => screen.getByRole('option', { name: 'hero.png' }))
    const picker = screen.getByRole('combobox', { name: 'Source Image' })
    const runButton = screen.getByRole('button', { name: 'Remove Background' })
    assert.equal((runButton as HTMLButtonElement).disabled, true)
    assert.match(screen.getByRole('status').textContent || '', /Choose an image from the library/i)
    assert.ok(screen.getByText('Upload an image'))
    assert.ok(screen.getByRole('option', { name: 'hero.png' }))

    fireEvent.change(picker, { target: { value: 'asset-hero' } })
    assert.equal(useStore.getState().toolsSourceAssetId, 'asset-hero')
    assert.equal(useStore.getState().toolsSourcePath, 'hero.png')
    assert.equal(useStore.getState().toolsSourceKind, 'image')
    assert.equal(useStore.getState().toolsSourceWorkspace, 'default')
    assert.ok(screen.getByRole('img', { name: 'hero.png' }))
    assert.equal((runButton as HTMLButtonElement).disabled, false)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})

test('video tools stay disabled when the selected source is an image', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ToolsPanel } = await import('../src/components/Sidebar/ToolsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const toolPosts: string[] = []
  globalThis.fetch = async input => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({ total: 0, assets: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    if (requestUrl.includes('/api/v1/tools/')) {
      toolPosts.push(requestUrl)
      return new Response(JSON.stringify({ job_id: 'should-not-run' }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${requestUrl}`)
  }
  useStore.setState({
    toolsTool: 'remove_background',
    toolsSourcePath: 'hero.png',
    toolsSourceName: 'hero.png',
    toolsSourceUrl: '/api/v1/file/hero.png',
    toolsSourceAssetId: 'asset-hero',
    toolsSourceWorkspace: 'default',
    toolsSourceKind: 'image',
    toolsRevoiceRefs: [{ filename: 'voice.wav', path: '/tmp/voice.wav' }, null],
    jobs: [],
    activeWorkspace: 'default',
    outputs: [],
    selectedOutput: -1,
  } as never)
  try {
    render(<ToolsPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'Upscale' }))
    assert.equal(useStore.getState().toolsTool, 'upscale')
    assert.equal(useStore.getState().toolsSourceKind, 'image')
    const upscaleButton = screen.getByRole('button', { name: 'Upscale Clip' })
    assert.equal(upscaleButton.disabled, true)
    fireEvent.click(upscaleButton)
    await useStore.getState().runTool()
    assert.deepEqual(toolPosts, [])

    fireEvent.click(screen.getByRole('button', { name: 'Revoice' }))
    assert.equal(useStore.getState().toolsTool, 'revoice')
    const revoiceButton = screen.getByRole('button', { name: 'Replace Voice' })
    assert.equal(revoiceButton.disabled, true)
    fireEvent.click(revoiceButton)
    await useStore.getState().runTool()
    assert.deepEqual(toolPosts, [])

    fireEvent.click(screen.getByRole('button', { name: 'Remove background' }))
    assert.equal(screen.getByRole('button', { name: 'Remove Background' }).disabled, false)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})

test('video tools can run only with a video source', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ToolsPanel } = await import('../src/components/Sidebar/ToolsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  globalThis.fetch = async input => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({ total: 0, assets: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${requestUrl}`)
  }
  useStore.setState({
    toolsTool: 'upscale',
    toolsSourcePath: 'clip.mp4',
    toolsSourceName: 'clip.mp4',
    toolsSourceUrl: '/api/v1/file/clip.mp4',
    toolsSourceAssetId: null,
    toolsSourceWorkspace: null,
    toolsSourceKind: 'video',
    toolsRevoiceRefs: [{ filename: 'voice.wav', path: '/tmp/voice.wav' }, null],
    activeWorkspace: 'default',
    outputs: [],
    selectedOutput: -1,
  } as never)
  try {
    render(<ToolsPanel />)
    assert.equal(screen.getByRole('button', { name: 'Upscale Clip' }).disabled, false)
    fireEvent.click(screen.getByRole('button', { name: 'Revoice' }))
    assert.equal(screen.getByRole('button', { name: 'Replace Voice' }).disabled, false)
    fireEvent.click(screen.getByRole('button', { name: 'Remove background' }))
    assert.equal(screen.getByRole('button', { name: 'Remove Background' }).disabled, true)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})

test('Tools submits background removal only once while the request is pending', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const previousSetInterval = globalThis.setInterval
  let submissions = 0
  let release!: (response: Response) => void
  const pending = new Promise<Response>(resolve => { release = resolve })
  globalThis.fetch = async input => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/tools/remove-background')) {
      submissions += 1
      return pending
    }
    throw new Error(`Unexpected request: ${requestUrl}`)
  }
  globalThis.setInterval = (() => 1) as unknown as typeof setInterval
  useStore.setState({
    toolsTool: 'remove_background', toolsSourcePath: 'hero.png', toolsSourceName: 'hero.png',
    toolsSourceUrl: '/api/v1/file/hero.png?workspace=default', toolsSourceAssetId: 'asset-hero',
    toolsSourceWorkspace: 'default', toolsSourceKind: 'image', toolsSubmitting: false,
    activeWorkspace: 'default', jobs: [],
  } as never)
  try {
    const first = useStore.getState().runTool()
    await new Promise(resolve => setTimeout(resolve, 0))
    const second = useStore.getState().runTool()
    assert.equal(submissions, 1)
    assert.equal(useStore.getState().toolsSubmitting, true)
    release(new Response(JSON.stringify({ job_id: 'job-bg-1' }), { status: 200 }))
    await first
    assert.equal(useStore.getState().toolsSubmitting, false)
    await second
  } finally {
    globalThis.fetch = previousFetch
    globalThis.setInterval = previousSetInterval
    useStore.setState({ toolsSubmitting: false, jobs: [] } as never)
  }
})
