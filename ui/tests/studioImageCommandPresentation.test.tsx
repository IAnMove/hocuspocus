import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
let nextFrameId = 1
const frameCallbacks = new Map<number, FrameRequestCallback>()
const requestAnimationFrame = (callback: FrameRequestCallback): number => {
  const id = nextFrameId++
  frameCallbacks.set(id, callback)
  return id
}
const cancelAnimationFrame = (id: number): void => { frameCallbacks.delete(id) }

Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
  MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage,
  React,
  requestAnimationFrame,
  cancelAnimationFrame,
  IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(dom.window, 'requestAnimationFrame', { configurable: true, value: requestAnimationFrame })
Object.defineProperty(dom.window, 'cancelAnimationFrame', { configurable: true, value: cancelAnimationFrame })
// The production bus clears a `window.setTimeout` with the browser-global
// `clearTimeout`.  Use the same Node timer realm in this JSDOM harness so a
// completed acknowledgement does not keep the test process alive for 8s.
Object.defineProperty(dom.window, 'setTimeout', { configurable: true, value: globalThis.setTimeout })
Object.defineProperty(dom.window, 'clearTimeout', { configurable: true, value: globalThis.clearTimeout })
Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: () => undefined })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { setUiLanguage } = await import('../src/i18n/index.ts')
await setUiLanguage('en')
const { createStudioImageGenerationCommand, pendingImageGenerationCommands, submitImageGenerationCommand } =
  await import('../src/api/imageGenerationCommands.ts')
const { StudioImageCommandPanel } = await import('../src/features/studio/StudioImageCommandPanel.tsx')
const { prepareStudioSubmission } = await import('../src/features/studio/imageCommandSubmission.ts')

const originalFetch = globalThis.fetch

async function flushAnimationFrames(): Promise<void> {
  // The panel deliberately waits for two browser frames.  Keep those frames
  // controllable so a test can change context or unmount before acknowledgement.
  for (let pass = 0; pass < 8 && frameCallbacks.size > 0; pass += 1) {
    const pending = [...frameCallbacks.entries()]
    frameCallbacks.clear()
    for (const [, callback] of pending) callback(0)
    await Promise.resolve()
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function baseParams(intent: string): Record<string, unknown> {
  return {
    workspace: 'studio-ack-workspace',
    prompt: `Literal prompt for ${intent}\nsecond line stays exact`,
    model_type: 'pi_flux2',
    resolution: '512x512',
    num_inference_steps: 4,
    guidance_scale: 1,
    seed: -1,
    image_mode: 1,
    video_length: 1,
    generation_mode: 'image',
    negative_prompt: '',
    repeat_generation: 1,
    batch_size: 1,
    activated_loras: ['style.safetensors'],
    loras_multipliers: '0.7',
    image_refs: [`asset_subject_${intent}`],
    canonical_image_refs: false,
  }
}

function command(intent: string) {
  return createStudioImageGenerationCommand(baseParams(intent), intent)
}

function queuedResponse(body: Record<string, unknown>): Response {
  const input = body.input as Record<string, unknown>
  const workspace = String(input.workspace)
  const intent = String(body.intent_id)
  const taskId = `task-${intent}`
  return jsonResponse({
    receipt: {
      version: 1,
      commandId: intent,
      operation: 'generation.image',
      status: 'queued',
      entities: [],
      artifacts: [],
      taskIds: [taskId],
      pipelineIds: [],
      result: { job_id: `job-${intent}`, task_id: taskId, workspace, status: 'queued' },
      commandVersion: 2,
      fingerprintVersion: 2,
      contentFingerprint: 'a'.repeat(64),
    },
    replayed: false,
  })
}

function formState(params: Record<string, unknown>) {
  return {
    params,
    activeWorkspace: params.workspace,
    generationMode: 'image',
    imageRefs: [],
    imageRefType: '',
    removeBackgroundRefs: false,
    loraWeights: {},
    spatialUpsampling: '',
    filmGrainIntensity: 0,
    filmGrainSaturation: 0.5,
    startImage: null,
    endImage: null,
  } as Parameters<typeof prepareStudioSubmission>[1]
}

function setSubmissionFetch(options: { failGeneration?: number } = {}) {
  const calls: Array<{ url: string; body?: Record<string, unknown> }> = []
  let generationCalls = 0
  let generationDom = ''
  let generationCommandAttribute: string | null = null
  globalThis.fetch = (async (input, init) => {
    const url = String(input)
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    calls.push({ url, body })
    if (url.includes('/api/v1/generation/commands/references')) {
      const references = body?.references
      return jsonResponse({ references: Array.isArray(references) ? references : [] })
    }
    if (url.includes('/api/v1/generation/commands')) {
      generationCalls += 1
      generationDom = document.body.textContent || ''
      generationCommandAttribute = document.querySelector('[data-studio-image-command]')?.getAttribute('data-studio-image-command') || null
      if (options.failGeneration === generationCalls) return jsonResponse({ detail: 'upstream unavailable' }, 503)
      return queuedResponse(body || {})
    }
    throw new Error(`Unexpected fetch in Studio image command test: ${url}`)
  }) as typeof fetch
  return {
    calls,
    generationCalls: () => generationCalls,
    generationDom: () => generationDom,
    generationCommandAttribute: () => generationCommandAttribute,
  }
}

test.afterEach(() => {
  frameCallbacks.clear()
  dom.window.localStorage.clear()
  globalThis.fetch = originalFetch
  document.body.replaceChildren()
})

test('renders the literal Studio snapshot and intent before the generation POST', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup, act } = await import('@testing-library/react')
  const params = baseParams('ack-before-post')
  const state = formState(params)
  const transport = setSubmissionFetch()
  render(<StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />)

  try {
    const prepared = await prepareStudioSubmission(params, state, () => state, {
      actor: 'wizard',
      commandId: 'ack-before-post',
    })
    let submission!: ReturnType<typeof prepared.submit>
    await act(async () => {
      submission = prepared.submit()
      await Promise.resolve()
    })

    await waitFor(() => {
      assert.equal(
        document.querySelector('[data-studio-image-command]')?.getAttribute('data-studio-image-command'),
        'ack-before-post',
      )
      assert.match(screen.getByRole('status').textContent || '', /Literal prompt for ack-before-post/)
      assert.match(screen.getByRole('status').textContent || '', /1 references · 1 LoRAs/)
    })
    assert.equal(transport.generationCalls(), 0, 'generation must wait for visible acknowledgement')

    await act(async () => { await flushAnimationFrames() })
    await submission

    assert.equal(transport.generationCalls(), 1)
    assert.match(transport.generationDom(), /Literal prompt for ack-before-post/)
    assert.doesNotMatch(transport.generationDom(), /previous submission needs recovery/i)
    assert.equal(transport.generationCommandAttribute(), 'ack-before-post')
    const generationBody = transport.calls.find(call => call.url.includes('/api/v1/generation/commands') && !call.url.includes('/references'))?.body
    assert.deepEqual(
      ((generationBody?.input as Record<string, unknown>).params as Record<string, unknown>).image_refs,
      ['asset_subject_ack-before-post'],
    )
  } finally {
    cleanup()
  }
})

test('a context change before the acknowledgement frame aborts without posting or retaining a hint', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup, act } = await import('@testing-library/react')
  const params = baseParams('context-change')
  const state = formState(params)
  const transport = setSubmissionFetch()
  const view = render(<StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />)

  try {
    const prepared = await prepareStudioSubmission(params, state, () => state, { actor: 'wizard', commandId: 'context-change' })
    let submission!: ReturnType<typeof prepared.submit>
    await act(async () => {
      submission = prepared.submit()
      await Promise.resolve()
    })
    const rejected = assert.rejects(submission, error => {
      assert.equal((error as { code?: string }).code, 'snapshot_hook_failed')
      return true
    })
    await waitFor(() => assert.match(screen.getByRole('status').textContent || '', /Literal prompt for context-change/))

    view.rerender(<StudioImageCommandPanel workspace="a-different-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />)
    await act(async () => { await flushAnimationFrames() })

    await rejected
    assert.equal(transport.generationCalls(), 0)
    assert.deepEqual(pendingImageGenerationCommands(), [])
  } finally {
    cleanup()
  }
})

test('unmounting while the snapshot is waiting cancels before admission', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup, act } = await import('@testing-library/react')
  const params = baseParams('unmount-before-post')
  const state = formState(params)
  const transport = setSubmissionFetch()
  const view = render(<StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />)

  try {
    const prepared = await prepareStudioSubmission(params, state, () => state, { actor: 'wizard', commandId: 'unmount-before-post' })
    let submission!: ReturnType<typeof prepared.submit>
    await act(async () => {
      submission = prepared.submit()
      await Promise.resolve()
    })
    const rejected = assert.rejects(submission, error => {
      assert.equal((error as { code?: string }).code, 'snapshot_hook_failed')
      return true
    })
    await waitFor(() => assert.match(screen.getByRole('status').textContent || '', /Literal prompt for unmount-before-post/))
    view.unmount()

    await rejected
    assert.equal(transport.generationCalls(), 0)
    assert.deepEqual(pendingImageGenerationCommands(), [])
  } finally {
    cleanup()
  }
})

test('a transient Suspense hide preserves the waiting request until the panel is visible again', { concurrency: false }, async () => {
  const { render, waitFor, cleanup, act } = await import('@testing-library/react')
  const never = new Promise<void>(() => undefined)
  function Sibling({ suspended }: { suspended: boolean }) {
    if (suspended) throw never
    return null
  }
  const tree = (suspended: boolean) => <React.StrictMode><React.Suspense fallback={<p>Loading</p>}>
    <StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />
    <Sibling suspended={suspended} />
  </React.Suspense></React.StrictMode>
  const params = baseParams('suspense-before-post')
  const state = formState(params)
  const transport = setSubmissionFetch()
  const view = render(tree(false))
  try {
    const prepared = await prepareStudioSubmission(params, state, () => state, { actor: 'wizard', commandId: 'suspense-before-post' })
    let submission!: ReturnType<typeof prepared.submit>
    let settled = false
    await act(async () => {
      submission = prepared.submit()
      void submission.then(() => { settled = true }, () => { settled = true })
    })
    await waitFor(() => assert.equal(document.querySelector('[data-studio-image-command]')?.getAttribute('data-studio-image-command'), 'suspense-before-post'))
    view.rerender(tree(true))
    await act(async () => { await flushAnimationFrames() })
    assert.equal(settled, false, 'a temporary hidden tree is not a cancelled request')
    assert.equal(transport.generationCalls(), 0)
    view.rerender(tree(false))
    await act(async () => { await flushAnimationFrames() })
    await submission
    assert.equal(transport.generationCalls(), 1)
  } finally { cleanup() }
})

test('a request started in a hidden Suspense tree waits for the receiver to reconnect', { concurrency: false }, async () => {
  const { render, waitFor, cleanup, act } = await import('@testing-library/react')
  const never = new Promise<void>(() => undefined)
  function Sibling({ suspended }: { suspended: boolean }) {
    if (suspended) throw never
    return null
  }
  const tree = (suspended: boolean) => <React.Suspense fallback={<p>Loading</p>}>
    <StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />
    <Sibling suspended={suspended} />
  </React.Suspense>
  const params = baseParams('start-while-hidden')
  const state = formState(params)
  const transport = setSubmissionFetch()
  const view = render(tree(false))
  try {
    view.rerender(tree(true))
    const prepared = await prepareStudioSubmission(params, state, () => state, { actor: 'wizard', commandId: 'start-while-hidden' })
    let submission!: ReturnType<typeof prepared.submit>
    await act(async () => { submission = prepared.submit() })
    assert.equal(transport.generationCalls(), 0)
    view.rerender(tree(false))
    await waitFor(() => assert.equal(document.querySelector('[data-studio-image-command]')?.getAttribute('data-studio-image-command'), 'start-while-hidden'))
    await act(async () => { await flushAnimationFrames() })
    await submission
    assert.equal(transport.generationCalls(), 1)
  } finally { cleanup() }
})

test('removing an already hidden Suspense tree cancels its pending acknowledgement', { concurrency: false }, async () => {
  const { render, waitFor, cleanup, act } = await import('@testing-library/react')
  const never = new Promise<void>(() => undefined)
  function Sibling({ suspended }: { suspended: boolean }) {
    if (suspended) throw never
    return null
  }
  const tree = (suspended: boolean) => <React.Suspense fallback={<p>Loading</p>}>
    <StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />
    <Sibling suspended={suspended} />
  </React.Suspense>
  const params = baseParams('unmount-after-hide')
  const state = formState(params)
  const transport = setSubmissionFetch()
  const view = render(tree(false))
  try {
    const prepared = await prepareStudioSubmission(params, state, () => state, { actor: 'wizard', commandId: 'unmount-after-hide' })
    let submission!: ReturnType<typeof prepared.submit>
    await act(async () => { submission = prepared.submit() })
    const rejected = assert.rejects(submission, error => (error as { code?: string }).code === 'snapshot_hook_failed')
    await waitFor(() => assert.equal(document.querySelector('[data-studio-image-command]')?.getAttribute('data-studio-image-command'), 'unmount-after-hide'))
    view.rerender(tree(true))
    view.unmount()
    await rejected
    assert.equal(transport.generationCalls(), 0)
    assert.deepEqual(pendingImageGenerationCommands(), [])
  } finally { cleanup() }
})

test('recovery reload reuses the exact intention after 503 and keeps its receipt if reconnect fails', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const saved = command('recovery-reload')
  let calls = 0
  const bodies: Record<string, unknown>[] = []
  globalThis.fetch = (async (_input, init) => {
    calls += 1
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>
    bodies.push(body)
    if (calls < 3) return jsonResponse({ detail: 'upstream unavailable' }, 503)
    return queuedResponse(body)
  }) as typeof fetch

  try {
    await assert.rejects(submitImageGenerationCommand(saved), error => {
      assert.equal((error as { uncertain?: boolean }).uncertain, true)
      return true
    })
    assert.deepEqual(pendingImageGenerationCommands(), [saved])

    const first = render(<StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => undefined} />)
    await waitFor(() => screen.getByRole('button', { name: 'Recover this submission' }))
    fireEvent.click(screen.getByRole('button', { name: 'Recover this submission' }))
    await waitFor(() => assert.match(screen.getByRole('alert').textContent || '', /upstream unavailable/))
    assert.equal(calls, 2)
    assert.deepEqual(bodies[1], saved)
    assert.deepEqual(pendingImageGenerationCommands(), [saved])

    // A remount models a reload: the durable hint, rather than current form
    // state, is the only source for the next explicit recovery.
    first.unmount()
    render(<StudioImageCommandPanel workspace="studio-ack-workspace" model="pi_flux2" visible onRecovered={async () => { throw new Error('reconnect failed') }} />)
    await waitFor(() => screen.getByRole('button', { name: 'Recover this submission' }))
    fireEvent.click(screen.getByRole('button', { name: 'Recover this submission' }))
    await waitFor(() => assert.match(screen.getByRole('alert').textContent || '', /reconnect failed/))

    assert.equal(calls, 3)
    assert.deepEqual(bodies[2], saved)
    assert.equal(pendingImageGenerationCommands().length, 0)
    assert.match(screen.getByRole('status').textContent || '', /Image queued · job-recovery-reload/)
  } finally {
    cleanup()
  }
})

test('frozen image request acknowledges in its target panel after a later model selection', { concurrency: false }, async () => {
  const { render, waitFor, cleanup, act } = await import('@testing-library/react')
  const { presentStudioImageCommand } = await import('../src/features/studio/imageCommandPresentation.ts')
  // A stale/hidden host must not reject the event meant for the visible host.
  render(<StudioImageCommandPanel workspace="studio-ack-workspace" model="stale-model" visible={false} onRecovered={async () => undefined} />)
  render(<StudioImageCommandPanel workspace="studio-ack-workspace" model="qwen_image_21" visible onRecovered={async () => undefined} />)
  const frozen = command('frozen-model-after-upload')
  try {
    let pending!: Promise<void>
    await act(async () => { pending = presentStudioImageCommand(frozen); await Promise.resolve() })
    await waitFor(() => assert.equal(document.querySelector('[data-studio-image-ready="true"]')?.getAttribute('data-studio-image-command'), frozen.intent_id))
    await act(async () => { await flushAnimationFrames() })
    await pending
    assert.match(document.querySelector('[data-studio-image-ready="true"]')?.textContent || '', /pi_flux2/)
    assert.equal(document.querySelector('[data-studio-image-ready="false"]')?.getAttribute('data-studio-image-command'), null)
  } finally { cleanup() }
})
