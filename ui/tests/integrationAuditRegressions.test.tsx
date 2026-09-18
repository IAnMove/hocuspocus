// Integration regressions without live models or providers.
import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { inspectAttempt } from '../src/features/generation-inspector/inspect.ts'
import { planRetry } from '../src/features/generation-inspector/clone.ts'
import { copyRecipe } from '../src/features/generation-inspector/recipe.ts'
import { submitInspectorPlan } from '../src/features/generation-inspector/submit.ts'
import { persistInspectedAttempt } from '../src/features/generation-inspector/persistence.ts'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import {
  createHistory, applyHistoryChange, historySaveState, persistHistoryDraft,
  readDraftPayload, restoreOrCreateHistory, type DraftStorage,
} from '../src/features/scene3d/documentHistory.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent, KeyboardEvent: dom.window.KeyboardEvent,
  MouseEvent: dom.window.MouseEvent, MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage, React, IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('the mounted inspector Generate action dispatches a generation', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup, act } = await import('@testing-library/react')
  const { GenerationInspectorHost } = await import('../src/features/generation-inspector/GenerationInspectorHost.tsx')
  const attempt = inspectAttempt({
    generation_id: 'audit-gen', output_folder: 'audit-workspace',
    prompt_original: 'A lantern', prompt_effective: 'A lantern',
    intent_id: 'audit-intent', model: { id: 'flux2', version: 'r1' }, mode: 'image',
    params: { resolution: '512x512', num_inference_steps: 1, guidance_scale: 1, seed: 1,
      generation_mode: 'image', image_mode: 1, video_length: 1 },
  }, { workspace: 'audit-workspace' })
  persistInspectedAttempt('audit-workspace', attempt, true)
  const previousFetch = globalThis.fetch
  const requests: string[] = []
  globalThis.fetch = async (input, options) => {
    requests.push(String(input))
    const command = JSON.parse(String(options?.body))
    assert.equal(command.input.workspace, 'audit-workspace')
    assert.equal(command.input.params.prompt, 'A lantern')
    assert.notEqual(command.intent_id, 'audit-intent')
    return new Response(JSON.stringify({ receipt: {
      version: 1, commandVersion: 2, fingerprintVersion: 2, contentFingerprint: 'a'.repeat(64),
      commandId: command.intent_id, operation: 'generation.image', status: 'queued',
      entities: [], artifacts: [], taskIds: ['task-audit'], pipelineIds: [],
      result: { job_id: 'job-audit', task_id: 'task-audit', workspace: 'audit-workspace', status: 'queued' },
    }, replayed: false }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    render(<GenerationInspectorHost workspace="audit-workspace" catalog={[]} currentModel={{ id: 'flux2', version: 'r1' }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Clone as new attempt' }))
    const button = screen.getByRole('button', { name: 'Generate' })
    assert.equal(button.hasAttribute('disabled'), false, 'Precondition: valid clone and enabled button')
    await act(async () => { fireEvent.click(button); await Promise.resolve() })
    assert.equal(requests.length, 1)
    assert.match(screen.getByRole('status').textContent || '', /task-audit/)
  } finally {
    globalThis.fetch = previousFetch
    cleanup()
  }
})

test('opening nine workspaces does not erase another workspace unsaved draft', { concurrency: false }, context => {
  let timestamp = 1000
  context.mock.method(Date, 'now', () => ++timestamp)
  const map = new Map<string, string>()
  const storage: DraftStorage = {
    getItem: key => map.get(key) ?? null,
    setItem: (key, value) => { map.set(key, value) },
    removeItem: key => { map.delete(key) },
  }
  const base = createDefaultScene3DDocument()
  const first = { workspace: 'audit-ws-0', documentId: 'audit-scene-0', revision: 0 }
  for (let index = 0; index < 9; index += 1) {
    const identity = { workspace: `audit-ws-${index}`, documentId: `audit-scene-${index}`, revision: 0 }
    let history = createHistory(base, identity, 'audit-tab')
    history = applyHistoryChange(history, { ...base, duration: base.duration + index + 1 })
    assert.equal(historySaveState(history), 'unsaved')
    history = persistHistoryDraft(history, storage)
    assert.equal(history.persistError, false)
    if (index === 0) assert.ok(readDraftPayload(storage, first))
  }
  const retained = readDraftPayload(storage, first)
  const restored = restoreOrCreateHistory(base, first.workspace, 'audit-tab', storage)
  console.log(JSON.stringify({ case: 'draft_eviction', firstDraftRetained: retained !== null,
    restoredDuration: restored.present.duration, unsavedDuration: base.duration + 1,
    restoredOriginalIdentity: restored.identity.documentId === first.documentId }))
  assert.ok(retained, 'Global LRU deletes the only unsaved copy without warning, including its backup')
})

test('inspector transport retry recovers the original receipt without reconstructing a command', { concurrency: false }, async () => {
  const attempt = inspectAttempt({
    generation_id: 'stored-generation', output_folder: 'original-folder', intent_id: 'stored-intent',
    prompt_original: 'literal original', prompt_effective: 'transformed prompt', mode: 'image',
  }, { workspace: 'original-folder' })
  const plan = planRetry(attempt, { workspace: 'original-folder' })
  const recipe = copyRecipe(attempt, attempt.attemptId)
  const before = globalThis.fetch
  let requests = 0
  globalThis.fetch = async (input, options) => {
    requests += 1
    assert.equal(options?.body, undefined)
    const url = new URL(String(input), 'http://localhost')
    assert.equal(url.searchParams.get('workspace'), 'original-folder')
    assert.equal(url.searchParams.get('intent_id'), 'stored-intent')
    if (requests === 2) return Response.json({ detail: { message: 'Clone to create a new attempt' } }, { status: 404 })
    return Response.json({ receipt: { commandId: 'stored-intent', result: { workspace: 'original-folder', task_id: 'original-task' } } })
  }
  try {
    assert.equal(await submitInspectorPlan(plan, recipe), 'original-task')
    await assert.rejects(submitInspectorPlan(plan, recipe), /Clone/)
    assert.equal(requests, 2)
  } finally { globalThis.fetch = before }
})
