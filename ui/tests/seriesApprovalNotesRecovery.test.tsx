import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { SeriesApprovalNotes } from '../src/features/series/SeriesApprovalNotes'

const dom = new JSDOM('', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('a rejected note survives remount and can be retried in its original scope', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  t.after(cleanup)
  let offline = true
  const saved: string[] = []
  const props = { draftKey: 'workspace/series/episode/shot/plan', shotId: 's1', stage: 'plan' as const,
    entry: { plan: 'pending' as const, preview: 'pending' as const, notes: [] },
    onSave: async (note: { text: string }) => { if (offline) throw Error('offline'); saved.push(note.text); return undefined } }
  let view = render(<SeriesApprovalNotes {...props} />)
  fireEvent.change(view.getByRole('textbox'), { target: { value: 'Keep this direction' } })
  await waitFor(() => assert.match(view.getByRole('status').textContent || '', /could not|failed|Couldn't/i), { timeout: 2000 })
  view.unmount()
  view = render(<SeriesApprovalNotes {...props} />)
  assert.equal((view.getByRole('textbox') as HTMLTextAreaElement).value, 'Keep this direction')
  offline = false
  fireEvent.click(view.getByRole('button', { name: 'Retry saving' }))
  await waitFor(() => assert.deepEqual(saved, ['Keep this direction']))
  view.unmount()
  view = render(<SeriesApprovalNotes {...props} draftKey="another-workspace/series/episode/shot/plan" />)
  assert.equal((view.getByRole('textbox') as HTMLTextAreaElement).value, '')
})

test('a late acknowledgement keeps newer text and serializes the next save with its assigned id', async () => {
  const { readApprovalNote, writeApprovalNote, saveApprovalNote } = await import('../src/features/series/approvalNoteDraft')
  const scope = 'late-note-ack'
  let finish!: (id: string) => void
  const sent: Array<{ text: string; id?: string }> = []
  writeApprovalNote(scope, 'First')
  const first = saveApprovalNote(scope, note => { sent.push(note); return new Promise<string>(resolve => { finish = resolve }) })
  await new Promise(resolve => setImmediate(resolve))
  writeApprovalNote(scope, 'Second')
  const second = saveApprovalNote(scope, async note => { sent.push(note); return note.id })
  assert.equal(sent.length, 1)
  finish('note-1')
  await first
  assert.equal(readApprovalNote(scope)?.text, 'Second')
  await second
  assert.equal(sent[1].text, 'Second')
  assert.equal(sent[1].id, 'note-1')
  assert.equal(readApprovalNote(scope), undefined)
})
