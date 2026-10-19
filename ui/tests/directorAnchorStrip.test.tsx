import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { SavedPipelineState } from '../src/types'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    HTMLImageElement: dom.window.HTMLImageElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function pipeline(overrides: Partial<SavedPipelineState> = {}): SavedPipelineState {
  return {
    version: 1, pipeline_id: 'run-1', created_at: 1, completed_at: 2, status: 'completed',
    pipeline_type: 'music_video', scene_description: 'A harbour at dawn', reference_image_path: null,
    auto_mode: true, seamless: false, image_model: 'qwen_image_21', video_model: 'ltx', llm_log: null,
    clips: [
      { index: 0, start_image_filename: 'shot-0.png' },
      { index: 1, start_image_filename: 'shot-1.png' },
    ] as SavedPipelineState['clips'],
    output_files: [], total_time_sec: 1,
    generation_details: {
      reference_anchor: { mode: 'always', source: 'generated', filename: 'anchor.png', prompt: 'Create a character reference for visual continuity.' },
      lighting_continuity: 'auto',
      keep_reference_wardrobe: true,
      chorus_set: 'first',
      coverage_cycle: ['wide', 'close-up'],
    },
    ...overrides,
  }
}

type Sent = { url: string; method?: string; body: unknown }

function mockFetch(sent: Sent[], status = 200) {
  const original = globalThis.fetch
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    sent.push({ url: String(input), method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : null })
    if (status !== 200) return new Response(JSON.stringify({ detail: 'Pick an image from this production' }), { status })
    return new Response(JSON.stringify(pipeline({
      generation_details: { reference_anchor: { mode: 'off', source: 'none' } },
    })), { headers: { 'content-type': 'application/json' } })
  }) as typeof fetch
  return () => { globalThis.fetch = original }
}

test('the strip shows the generated reference, its prompt and the run options', { concurrency: false }, async t => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { DirectorAnchorStrip } = await import('../src/features/director/DirectorAnchorStrip.tsx')
  t.after(cleanup)
  render(<DirectorAnchorStrip pipeline={pipeline()} workspace="film" onSaved={() => {}} />)
  assert.ok(screen.getByText('Made automatically from shot 1. Every shot is drawn from this picture.'))
  assert.ok(screen.getByText(/Prompt: Create a character reference/))
  const options = screen.getByText(/^Setting: /).textContent || ''
  assert.match(options, /Setting: Always \(default\)/)
  assert.match(options, /Light: Auto: only with your reference image/)
  assert.match(options, /Clothes: copied from the references/)
  assert.match(options, /Choruses: Return to the first set \(default\)/)
  assert.match(options, /Coverage cycle: 2 lines/)
  const image = document.querySelector('section img') as HTMLImageElement
  assert.match(image.src, /\/api\/v1\/file\/anchor\.png$/)
})

test('Replace sends a picture of the run and Clear sends none', { concurrency: false }, async t => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { DirectorAnchorStrip } = await import('../src/features/director/DirectorAnchorStrip.tsx')
  const sent: Sent[] = []
  const restore = mockFetch(sent)
  t.after(() => { restore(); cleanup() })
  const saved: SavedPipelineState[] = []
  render(<DirectorAnchorStrip pipeline={pipeline()} workspace="film" onSaved={value => saved.push(value)} />)

  fireEvent.click(screen.getByRole('button', { name: 'Replace…' }))
  fireEvent.click(screen.getByRole('button', { name: 'Use shot 2 as the shared reference' }))
  await waitFor(() => assert.equal(saved.length, 1))
  assert.equal(sent[0].method, 'PUT')
  assert.match(sent[0].url, /\/api\/v1\/director\/pipelines\/run-1\/anchor$/)
  assert.deepEqual(sent[0].body, { workspace: 'film', filename: 'shot-1.png' })

  fireEvent.click(screen.getByRole('button', { name: /Stop using it for repairs/ }))
  await waitFor(() => assert.equal(saved.length, 2))
  assert.deepEqual(sent[1].body, { workspace: 'film', filename: null })
  assert.equal(saved[1].generation_details?.reference_anchor?.source, 'none')
})

test('a refused change is shown, not swallowed', { concurrency: false }, async t => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { DirectorAnchorStrip } = await import('../src/features/director/DirectorAnchorStrip.tsx')
  const restore = mockFetch([], 422)
  t.after(() => { restore(); cleanup() })
  render(<DirectorAnchorStrip pipeline={pipeline()} workspace="film" onSaved={() => assert.fail('not saved')} />)
  fireEvent.click(screen.getByRole('button', { name: /Stop using it for repairs/ }))
  const alert = await screen.findByRole('alert')
  assert.match(alert.textContent || '', /Could not change the shared reference: Pick an image from this production/)
})

test("the user's own reference has no Replace or Clear", { concurrency: false }, async t => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { DirectorAnchorStrip } = await import('../src/features/director/DirectorAnchorStrip.tsx')
  t.after(cleanup)
  render(<DirectorAnchorStrip
    pipeline={pipeline({ generation_details: { reference_anchor: { mode: 'always', source: 'user', filename: 'me.png' } } })}
    workspace="film" onSaved={() => {}} />)
  assert.ok(screen.getByText('Your reference image. Every shot is drawn from it.'))
  assert.equal(screen.queryByRole('button', { name: 'Replace…' }), null)
  assert.equal(screen.queryByRole('button', { name: /Stop using it/ }), null)
  assert.match((document.querySelector('section img') as HTMLImageElement).src, /me\.png\?workspace=__uploads__$/)
})

test('off shows each shot from its own prompt; older runs show nothing', { concurrency: false }, async t => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { DirectorAnchorStrip, PlanFallbackNotice } = await import('../src/features/director/DirectorAnchorStrip.tsx')
  t.after(cleanup)
  render(<DirectorAnchorStrip
    pipeline={pipeline({ generation_details: { reference_anchor: { mode: 'off', source: 'none' }, coverage_cycle: [] } })}
    workspace="film" onSaved={() => {}} />)
  assert.ok(screen.getByText('No shared reference: each shot is drawn from its own prompt.'))
  assert.match(screen.getByText(/^Setting: /).textContent || '', /Off: each shot from its own prompt · Coverage cycle: the planner chooses/)
  assert.equal(screen.queryByRole('button', { name: /Stop using it/ }), null)
  cleanup()
  const { container } = render(<DirectorAnchorStrip pipeline={pipeline({ generation_details: undefined })} workspace="film" onSaved={() => {}} />)
  assert.equal(container.innerHTML, '')
  cleanup()
  render(<PlanFallbackNotice pipeline={pipeline({ planning_source: 'deterministic_fallback' })} />)
  assert.ok(screen.getByText('The planner returned no shots; Director built a simple plan from the story.'))
})
