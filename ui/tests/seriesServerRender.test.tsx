import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('a stopped server render is found again, explains the failed shot and resumes', async t => {
  const { render, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { SeriesServerRender } = await import('../src/features/series/SeriesServerRender')
  t.after(cleanup)
  const calls: string[] = []
  const failed = { jobId: 'native-1', seriesId: 'uv', episodeId: 'ep1', current: 2, total: 2, status: 'failed', createdAt: 2,
    items: [{ shotId: 's01', stage: 'done', status: 'done' }, { shotId: 's02', stage: 'export', status: 'failed', error: 'browser crashed' }] }
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push(`${init?.method ?? 'GET'} ${url.replace(/^.*\/api\/v1/, '')}`)
    const body = url.includes('/recovery') ? { jobs: [{ ...failed, episodeId: 'other' }, failed] }
      : url.endsWith('/resume') ? { ...failed, status: 'queued', items: [failed.items[0], { ...failed.items[1], status: 'queued', error: null }] } : failed
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  const series = { id: 'uv' } as never, episode = { id: 'ep1' } as never
  const view = render(<SeriesServerRender workspace="cast" series={series} episode={episode} />)
  await waitFor(() => assert.ok(view.getByTestId('server-render-s02').textContent?.includes('browser crashed')))
  assert.match(view.getByRole('status').textContent ?? '', /1 of 2 shots · some shots failed/)
  fireEvent.click(view.getByRole('button', { name: 'Resume' }))
  await waitFor(() => assert.match(view.getByRole('status').textContent ?? '', /queued/))
  assert.ok(calls.includes('POST /series/native-render/jobs/native-1/resume'))
  assert.equal((view.getByRole('button', { name: 'Render on the server' }) as HTMLButtonElement).disabled, true, 'one render at a time')
})
