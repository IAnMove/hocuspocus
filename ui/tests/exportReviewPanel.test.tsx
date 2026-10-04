import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { contactMarks, joinExportReview, type ExportReviewInput } from '../src/features/render/exportReview.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement, Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

const receipt: ExportReviewInput = {
  qa: { verdict: 'fail', warnings: [{ code: 'black', t: 0, detail: 'black frame' }, { code: 'still', t: 1 }] },
  geometry: { verdict: 'watch', warnings: [{ code: 'floating', severity: 'watch', slot: 'hero', start: 3, end: 5, detail: 'above the floor' }] },
}

test('fail warnings sort ahead of watch warnings and allowed probes stay out', () => {
  const items = joinExportReview(receipt)
  assert.deepEqual(items.map(item => item.code), ['black', 'floating'])
  assert.deepEqual(items.map(item => item.severity), ['fail', 'watch'])
  const marks = contactMarks(7, items)
  assert.equal(marks[0]?.severity, 'fail')
  assert.equal(marks[4]?.time, 4)
  assert.equal(marks[4]?.severity, 'watch')
  assert.equal(marks[6]?.severity, 'ok')
})

test('the review panel seeks from a warning and a marked cell and never asks to confirm', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ExportReviewPanel } = await import('../src/features/render/ExportReviewPanel.tsx')
  const sought: number[] = []
  try {
    render(<div>
      <button type="button">Export</button>
      <ExportReviewPanel review={receipt} duration={7} onSeek={time => sought.push(time)} />
    </div>)
    const warnings = screen.getAllByTestId('export-review-warning')
    assert.equal(warnings[0]?.getAttribute('data-severity'), 'fail')
    assert.equal(warnings[1]?.getAttribute('data-severity'), 'watch')
    fireEvent.click(warnings[0]!)
    const marked = screen.getAllByTestId('export-review-mark').find(cell => cell.getAttribute('data-severity') === 'watch')
    assert.ok(marked)
    fireEvent.click(marked!)
    assert.equal(sought[0], 0)
    assert.equal(sought[1], 3)
    assert.equal(screen.queryByRole('button', { name: /confirm|block export|confirmar|bloquear/i }), null)
    assert.equal(screen.getByRole('button', { name: 'Export' }).hasAttribute('disabled'), false)
    assert.equal(screen.getByText('These warnings do not block export.').textContent?.includes('do not block'), true)
  } finally { cleanup() }
})

test('a clean receipt shows the hint and an unreliable measurement stays a warning', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ExportReviewPanel } = await import('../src/features/render/ExportReviewPanel.tsx')
  try {
    const { rerender } = render(<ExportReviewPanel review={{ qa: { verdict: 'ok', warnings: [] } }} duration={4} onSeek={() => undefined} />)
    assert.equal(screen.getByText('This export has no warnings.').textContent?.length > 0, true)
    assert.equal(screen.queryByTestId('export-review-warning'), null)
    rerender(<ExportReviewPanel review={{ qa: { verdict: 'unreliable', warnings: [], reason: 'no ffmpeg' } }} duration={4} onSeek={() => undefined} />)
    assert.equal(screen.getByText(/no ffmpeg/).textContent?.includes('no ffmpeg'), true)
    assert.equal(screen.queryByRole('button', { name: /confirm|block export/i }), null)
    rerender(<ExportReviewPanel review={null} duration={4} onSeek={() => undefined} />)
    assert.equal(screen.queryByTestId('export-review'), null)
  } finally { cleanup() }
})
