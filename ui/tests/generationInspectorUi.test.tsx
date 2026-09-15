import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { inspectAttempt } from '../src/features/generation-inspector/inspect.ts'
import { persistInspectedAttempt, clearInspectedAttempt, openGenerationInspector } from '../src/features/generation-inspector/persistence.ts'

const clipboard: string[] = []
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
  KeyboardEvent: dom.window.KeyboardEvent,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage,
  React,
  IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
Object.defineProperty(dom.window.navigator, 'clipboard', {
  configurable: true,
  value: { writeText: async (value: string) => { clipboard.push(value) } },
})

const source = {
  generation_id: 'gen_choir',
  output_folder: 'night-shift',
  prompt_original: 'user choir',
  prompt_effective: 'cinematic choir, night',
  intent_id: 'intent-choir',
  model: { id: 'flux2', version: 'r1' },
  params: {
    image_refs: [{ asset_id: 'asset_gone', filename: 'hero.png' }],
    resolution: '720p',
    api_key: 'do-not-save',
  },
  transforms: [{ source: 'policy', field: 'prompt', before: 'user choir', after: 'cinematic choir, night' }],
}

const other = {
  generation_id: 'gen_metal',
  output_folder: 'night-shift',
  prompt_original: 'user choir',
  prompt_effective: 'metal choir',
  intent_id: 'intent-metal',
  model: { id: 'qwen', version: 'r2' },
}

const catalog = [{ assetId: 'asset_first', filename: 'first.png', workspace: 'night-shift' }]

test('inspector UI shows original vs effective, unknown, clone intent and missing refs', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { GenerationInspectorDialog } = await import('../src/features/generation-inspector/GenerationInspectorDialog.tsx')
  const attempt = inspectAttempt(source, { workspace: 'night-shift', catalog })
  const compare = inspectAttempt(other, { workspace: 'night-shift' })
  try {
    render(
      <GenerationInspectorDialog
        open
        onClose={() => undefined}
        attempt={attempt}
        workspace="night-shift"
        catalog={catalog}
        currentModel={{ id: 'qwen', version: 'r9' }}
        candidates={[attempt, compare]}
      />,
    )
    assert.ok(screen.getByRole('dialog', { name: 'Prompt and recipe inspector' }))
    assert.match(screen.getByText('Original request').parentElement?.textContent || '', /user choir/)
    assert.match(screen.getByText('Effective prompt').parentElement?.textContent || '', /cinematic choir, night/)
    assert.match(screen.getByTestId('inspector-changes').textContent || '', /Policy/)
    assert.match(screen.getByTestId('inspector-refs').textContent || '', /Missing — not replaced from the catalog/)
    fireEvent.click(screen.getByRole('button', { name: 'Clone as new attempt' }))
    const clonePlan = screen.getByTestId('inspector-plan')
    assert.match(clonePlan.textContent || '', /New intent/)
    assert.equal((clonePlan.textContent || '').includes('intent-choir'), false)
    fireEvent.click(screen.getByRole('button', { name: 'Transport retry' }))
    assert.match(screen.getByTestId('inspector-plan').textContent || '', /Same intent: intent-choir/)
    assert.match(screen.getByTestId('inspector-preflight').textContent || '', /Preflight blocked generate/)
    assert.ok(screen.getByRole('button', { name: 'Generate' }).hasAttribute('disabled'))
    fireEvent.change(screen.getByDisplayValue('None'), { target: { value: 'gen_metal' } })
    assert.match(screen.getByTestId('inspector-diff').textContent || '', /effectivePrompt/)
    fireEvent.click(screen.getByRole('button', { name: 'Copy recipe' }))
    await screen.findByText(/Recipe copied/)
    assert.equal(clipboard.some(item => item.includes('hero.png') && !item.includes('do-not-save')), true)
  } finally {
    cleanup()
  }
})

test('unknown original is shown and never filled from the output caption', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { GenerationInspectorDialog } = await import('../src/features/generation-inspector/GenerationInspectorDialog.tsx')
  const attempt = inspectAttempt({
    generation_id: 'gen_loose',
    output_folder: 'night-shift',
    prompt_effective: 'cinematic choir, night',
    output: { caption: 'a choir singing on stage' },
  }, { workspace: 'night-shift' })
  try {
    render(
      <GenerationInspectorDialog
        open
        onClose={() => undefined}
        attempt={attempt}
        workspace="night-shift"
      />,
    )
    assert.match(screen.getByText('Original request').parentElement?.textContent || '', /unknown/)
    assert.equal(screen.queryByText('a choir singing on stage'), null)
  } finally {
    cleanup()
  }
})

test('host restores the inspected attempt after reload and drops the other folder', { concurrency: false }, async () => {
  const { render, screen, cleanup, act } = await import('@testing-library/react')
  const { GenerationInspectorHost } = await import('../src/features/generation-inspector/GenerationInspectorHost.tsx')
  const attempt = inspectAttempt(source, { workspace: 'night-shift', catalog })
  persistInspectedAttempt('night-shift', attempt, true)
  try {
    const view = render(<GenerationInspectorHost workspace="night-shift" catalog={catalog} />)
    assert.ok(screen.getByRole('dialog', { name: 'Prompt and recipe inspector' }))
    assert.match(screen.getByText('Original request').parentElement?.textContent || '', /user choir/)
    view.rerender(<GenerationInspectorHost workspace="other-folder" catalog={catalog} />)
    assert.equal(screen.queryByRole('dialog'), null)
    act(() => openGenerationInspector({ workspace: 'night-shift', source }))
    assert.equal(screen.queryByRole('dialog'), null)
  } finally {
    clearInspectedAttempt('night-shift')
    cleanup()
  }
})
