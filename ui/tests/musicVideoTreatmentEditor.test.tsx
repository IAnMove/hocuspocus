import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { MusicVideoTreatment } from '../src/types'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

const TREATMENT: MusicVideoTreatment = {
  generation_mode: 'image_guided', direct_video_master_prompt: '', mode: 'hybrid', performer_presence: 60,
  lip_sync: 'frequent', recurring_sets: ['Main performance set', 'Story world'], wardrobe: '', palette: '',
  camera_language: '', recurring_motif: '', chorus_signature: '', surrealism: 35, forbidden_elements: '',
}

test('the treatment editor shows and edits the coverage cycle and the chorus sets', { concurrency: false }, async t => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { MusicVideoTreatmentEditor, TreatmentSummary } = await import('../src/features/director/MusicVideoTreatmentEditor.tsx')
  const { DEFAULT_COVERAGE_CYCLE } = await import('../src/features/director/treatmentDefaults.ts')
  t.after(cleanup)
  const changes: Array<Partial<MusicVideoTreatment>> = []
  render(<MusicVideoTreatmentEditor treatment={TREATMENT} onChange={change => changes.push(change)} />)

  // A treatment without the field shows the six lines the server will use.
  const coverage = screen.getByLabelText(/Coverage cycle · one per line/) as HTMLTextAreaElement
  assert.equal(coverage.value, DEFAULT_COVERAGE_CYCLE.join('\n'))
  assert.ok(screen.getByText('Clip 1 gets the first line, clip 2 the second… Empty: the planner chooses.'))

  fireEvent.change(coverage, { target: { value: ' wide \nclose-up\n' } })
  assert.deepEqual(changes.at(-1), { coverage: ['wide', 'close-up'] })
  assert.equal(coverage.value, ' wide \nclose-up\n')  // what is typed stays, including the new line
  fireEvent.change(coverage, { target: { value: '' } })
  assert.deepEqual(changes.at(-1), { coverage: [] })

  const choruses = screen.getByLabelText('Choruses') as HTMLSelectElement
  assert.equal(choruses.value, 'first')
  assert.deepEqual([...choruses.options].map(option => option.text), [
    'Return to the first set (default)', 'Rotate through the sets', 'The planner chooses',
  ])
  fireEvent.change(choruses, { target: { value: 'rotate' } })
  assert.deepEqual(changes.at(-1), { chorus_set: 'rotate' })

  // The labels that used to be hard-coded English come from the catalog.
  assert.ok(screen.getByText('Music-video treatment'))
  assert.ok(screen.getByLabelText(/Recurring sets · one per line/))
  cleanup()
  render(<p><TreatmentSummary treatment={TREATMENT} /></p>)
  assert.ok(screen.getByText('Hybrid · 60% performance · 2 recurring sets'))
})

test('a saved cycle is shown as saved', { concurrency: false }, async t => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { MusicVideoTreatmentEditor } = await import('../src/features/director/MusicVideoTreatmentEditor.tsx')
  t.after(cleanup)
  render(<MusicVideoTreatmentEditor treatment={{ ...TREATMENT, coverage: [], chorus_set: 'free' }} onChange={() => {}} />)
  assert.equal((screen.getByLabelText(/Coverage cycle/) as HTMLTextAreaElement).value, '')
  assert.equal((screen.getByLabelText('Choruses') as HTMLSelectElement).value, 'free')
})
