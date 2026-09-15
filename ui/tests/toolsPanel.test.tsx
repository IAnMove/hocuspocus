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
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLImageElement: dom.window.HTMLImageElement,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    MutationObserver: dom.window.MutationObserver,
    requestAnimationFrame: (callback: FrameRequestCallback) => setTimeout(() => callback(Date.now()), 0),
    cancelAnimationFrame: (handle: number) => clearTimeout(handle),
    localStorage: dom.window.localStorage,
    ResizeObserver: class { observe() {} disconnect() {} },
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('Tools exposes exact library images for background removal', { concurrency: false }, async () => {
  const { render, cleanup } = await import('@testing-library/react')
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
          prompt_preview: 'hero', manifest: { technical: { width: 1920, height: 1080 } },
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  useStore.setState({
    toolsTool: 'remove_background', toolsSourcePath: null, toolsSourceName: null,
    toolsSourceUrl: null, toolsSourceAssetId: null, toolsSourceWorkspace: null, toolsSourceKind: null,
    toolsSubmitting: false,
    activeWorkspace: 'default', outputs: [], selectedOutput: -1,
  } as never)
  try {
    render(<ToolsPanel />)
    const buttonByText = (label: string) => {
      const match = [...document.querySelectorAll('button')].find(button => button.textContent?.includes(label))
      assert.ok(match, label)
      return match as HTMLButtonElement
    }
    const runButton = buttonByText('Remove Background')
    assert.equal(runButton.disabled, true)
    assert.ok(buttonByText('From HocusPocus'))
    assert.ok(buttonByText('From my computer'))
    assert.match(document.querySelector('[role="status"]')?.textContent || '', /Choose an image or video from the library/i)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})

test('upscale accepts an image while revoice remains video-only', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { ToolsPanel } = await import('../src/components/Sidebar/ToolsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const previousSetInterval = globalThis.setInterval
  const commandPosts: Array<{ url: string; body?: Record<string, unknown> }> = []
  globalThis.fetch = async (input, init) => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({ total: 0, assets: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    if (requestUrl.includes('/api/v1/generation/commands')) {
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
      commandPosts.push({ url: requestUrl, body })
      const commandId = String(body?.intent_id || '')
      return new Response(JSON.stringify({
        version: 1,
        commandId,
        operation: 'tools.upscale',
        status: 'queued',
        entities: [],
        artifacts: [],
        taskIds: ['task-upscale-1'],
        pipelineIds: [],
        result: {
          job_id: 'image-upscale-1', task_id: 'task-upscale-1',
          workspace: 'default', status: 'queued',
        },
        commandVersion: 2,
        contentFingerprint: 'a'.repeat(64),
        fingerprintVersion: 2,
      }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
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
    generationMode: 'tools',
    outputs: [],
    selectedOutput: -1,
  } as never)
  globalThis.setInterval = (() => 1) as unknown as typeof setInterval
  try {
    render(<ToolsPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'Upscale' }))
    assert.equal(useStore.getState().toolsTool, 'upscale')
    assert.equal(useStore.getState().toolsSourceKind, 'image')
    const upscaleButton = screen.getByRole('button', { name: 'Upscale Image' })
    assert.equal(upscaleButton.disabled, false)
    fireEvent.click(upscaleButton)
    await waitFor(() => assert.equal(commandPosts.length, 1), { timeout: 2000 })
    assert.equal(commandPosts.length, 1)
    assert.equal(commandPosts[0].url, '/api/v1/generation/commands')
    assert.equal(commandPosts[0].body?.version, 2)
    assert.equal(commandPosts[0].body?.operation, 'tools.upscale')
    const commandInput = commandPosts[0].body?.input as Record<string, unknown>
    const commandParams = commandInput.params as Record<string, unknown>
    assert.equal(commandInput.workspace, 'default')
    assert.equal(commandParams.source, 'asset-hero')
    assert.equal(commandParams.source_workspace, 'default')
    assert.equal(commandParams.source_kind, 'image')
    assert.equal(commandParams.method, 'flashvsr2')
    assert.equal(commandParams.video_path, undefined)

    fireEvent.click(screen.getByRole('button', { name: 'Revoice' }))
    assert.equal(useStore.getState().toolsTool, 'revoice')
    const revoiceButton = screen.getByRole('button', { name: 'Replace Voice' })
    assert.equal(revoiceButton.disabled, true)
    fireEvent.click(revoiceButton)
    await useStore.getState().runTool()
    assert.equal(commandPosts.length, 1)

    fireEvent.click(screen.getByRole('button', { name: /^Remove background$/ }))
    await new Promise(resolve => setTimeout(resolve, 0))
    assert.equal(screen.getByRole('button', { name: /^Remove Background$/ }).disabled, false)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
    globalThis.setInterval = previousSetInterval
  }
})

test('quick video upscale enters Tools and presents one durable command', { concurrency: false }, async () => {
  const { render, cleanup, waitFor } = await import('@testing-library/react')
  const { ToolsPanel } = await import('../src/components/Sidebar/ToolsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const previousSetInterval = globalThis.setInterval
  const commandPosts: Array<Record<string, unknown>> = []
  globalThis.fetch = async (input, init) => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({ total: 0, assets: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    if (requestUrl.includes('/api/v1/generation/commands')) {
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}
      commandPosts.push(body)
      return new Response(JSON.stringify({
        version: 1,
        commandId: String(body.intent_id || ''),
        operation: 'tools.upscale',
        status: 'queued',
        entities: [],
        artifacts: [],
        taskIds: ['task-quick-upscale'],
        pipelineIds: [],
        result: {
          job_id: 'job-quick-upscale', task_id: 'task-quick-upscale',
          workspace: 'default', status: 'queued',
        },
        commandVersion: 2,
        contentFingerprint: 'b'.repeat(64),
        fingerprintVersion: 2,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  globalThis.setInterval = (() => 1) as unknown as typeof setInterval
  useStore.setState({
    generationMode: 'video',
    sidebarMode: 'director', sidebarOpen: false, settingsOpen: true, dashboardOpen: true,
    toolsTool: 'upscale',
    toolsSourcePath: null, toolsSourceName: null, toolsSourceUrl: null,
    toolsSourceAssetId: null, toolsSourceWorkspace: null, toolsSourceKind: null,
    toolsUpscaleMethod: 'flashvsr2', toolsSubmitting: false,
    activeWorkspace: 'default', jobs: [], outputs: [], selectedOutput: -1,
  } as never)
  try {
    render(<ToolsPanel />)
    await waitFor(() => assert.equal(
      document.querySelector('[data-studio-tools-listening="true"]')?.getAttribute('data-studio-tools-listening'),
      'true',
    ))
    await useStore.getState().quickUpscaleClip(
      'clip.mp4', '/api/v1/file/clip.mp4?workspace=default',
    )
    assert.equal(useStore.getState().generationMode, 'tools')
    assert.equal(useStore.getState().sidebarMode, 'studio')
    assert.equal(useStore.getState().sidebarOpen, true)
    assert.equal(useStore.getState().settingsOpen, false)
    assert.equal(useStore.getState().dashboardOpen, false)
    assert.equal(commandPosts.length, 1)
    assert.equal(commandPosts[0].version, 2)
    assert.equal(commandPosts[0].operation, 'tools.upscale')
    const input = commandPosts[0].input as Record<string, unknown>
    const params = input.params as Record<string, unknown>
    assert.equal(input.workspace, 'default')
    assert.equal(params.source, '/api/v1/file/clip.mp4?workspace=default')
    assert.equal(params.source_kind, 'video')
    assert.equal(params.method, 'flashvsr2')
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
    globalThis.setInterval = previousSetInterval
    useStore.setState({ toolsSubmitting: false, jobs: [] } as never)
  }
})

test('video tools can run only with a video source', { concurrency: false }, async () => {
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
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
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
    fireEvent.click(screen.getByRole('button', { name: /^Remove background$/ }))
    assert.equal(screen.getByRole('button', { name: /^Remove Background$/ }).disabled, false)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})

for (const kind of ['image', 'video'] as const) {
test(`Tools submits ${kind} background removal only once while pending`, { concurrency: false }, async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const previousSetInterval = globalThis.setInterval
  const filename = kind === 'video' ? 'hero.mp4' : 'hero.png'
  let submissions = 0
  let release!: (response: Response) => void
  const pending = new Promise<Response>(resolve => { release = resolve })
  globalThis.fetch = async input => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/tools/remove-background')) {
      submissions += 1
      return pending
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  globalThis.setInterval = (() => 1) as unknown as typeof setInterval
  useStore.setState({
    toolsTool: 'remove_background', toolsSourcePath: filename, toolsSourceName: filename,
    toolsSourceUrl: `/api/v1/file/${filename}?workspace=default`, toolsSourceAssetId: 'asset-hero',
    toolsSourceWorkspace: 'default', toolsSourceKind: kind, toolsSubmitting: false,
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
}

test('remote catalog picks past the local 100-item cache keep workspace identity', async () => {
  const { resolveToolSource } = await import('../src/lib/toolSource.ts')
  const remote = {
    name: 'wanted.png',
    type: 'image' as const,
    mode: null,
    size: 12,
    created_at: 1,
    url: '/api/v1/file/wanted.png?workspace=film',
    thumbnail_url: '/api/v1/file/wanted.png?workspace=film',
    asset_id: 'asset-110',
    workspace_id: 'film',
    path: 'wanted.png',
  }
  const source = resolveToolSource(remote, [], 'film')
  assert.equal(source.assetId, 'asset-110')
  assert.equal(source.workspace, 'film')
  assert.equal(source.path, 'wanted.png')
  assert.equal(source.kind, 'image')
})

test('device uploads without a catalog id still resolve under uploads', async () => {
  const { resolveToolSource } = await import('../src/lib/toolSource.ts')
  const uploaded = {
    name: 'from-disk.png',
    type: 'image' as const,
    mode: null,
    size: 8,
    created_at: 1,
    url: '/api/v1/uploads/from-disk.png',
    thumbnail_url: '/api/v1/uploads/from-disk.png',
    workspace_id: 'film',
    path: 'uploads/from-disk.png',
  }
  const source = resolveToolSource(uploaded, [], 'film')
  assert.equal(source.assetId, null)
  assert.equal(source.workspace, '__uploads__')
  assert.equal(source.path, 'from-disk.png')
})
