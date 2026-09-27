import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  localStorage: dom.window.localStorage,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { render, fireEvent, cleanup } = await import('@testing-library/react')
const { projectStudioH3RequestParams } = await import('../src/lib/h3OptionalSettings.ts')
const { useStore } = await import('../src/stores/useStore.ts')
const { H3PromptControls } = await import('../src/components/Sidebar/H3PromptControls.tsx')

const SPOKEN = 'Alice (S1): «Buenos días»\nBob whispers "keep this line".'

function requestFrom(params: Record<string, unknown>) {
  return projectStudioH3RequestParams({
    prompt: SPOKEN,
    model_type: 'minimax_h3',
    ...params,
  })
}

test('each Studio H3 control lands on the generation request', () => {
  const before = useStore.getState()
  try {
    useStore.setState({
      params: { ...before.params, model_type: 'minimax_h3', prompt: SPOKEN },
      isEnhancing: false,
    })
    const view = render(React.createElement(H3PromptControls))
    const selects = view.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: 'creative' } })
    fireEvent.change(selects[1], { target: { value: 'legacy' } })
    const request = requestFrom(useStore.getState().params as Record<string, unknown>)
    assert.equal(request.minimax_h3_planning_style, 'creative')
    assert.equal(request.minimax_h3_audio_policy, 'legacy')
    assert.equal(request.prompt, SPOKEN)
    assert.equal(request.minimax_h3_semantic_bridge_alpha, 0)
  } finally {
    cleanup()
    useStore.setState(before)
  }
})

test('invalid Studio H3 enums fall back and do not rewrite spoken text', () => {
  const request = requestFrom({
    minimax_h3_planning_style: 'bogus',
    minimax_h3_audio_policy: 'maybe',
    minimax_h3_semantic_bridge_alpha: 4,
  })
  assert.equal(request.minimax_h3_planning_style, 'faithful')
  assert.equal(request.minimax_h3_audio_policy, 'native')
  assert.equal(request.minimax_h3_semantic_bridge_alpha, 0)
  assert.equal(request.prompt, SPOKEN)
})

test('Semantic Bridge stays off by default even on a supported model', () => {
  const request = requestFrom({})
  assert.equal(request.minimax_h3_semantic_bridge_alpha, 0)
  assert.equal(request.minimax_h3_semantic_bridge_magnitude, 'per_token')
})
