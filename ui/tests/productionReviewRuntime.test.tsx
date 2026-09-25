import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { applyPersistCommands } from '../src/features/production-review/persist'
import { projectReviewDesk } from '../src/features/production-review/project'
import { restoreCompareChoices, selectExactTake } from '../src/features/production-review/takes'
import { exportApprovedSelection } from '../src/features/production-review/exportSelection'
import { regenerateReview } from '../src/features/production-review/runtime'
import type { SavedPipelineState } from '../src/types'
import type { PipelineLike } from '../src/features/production-review/types'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage, React, IS_REACT_ACT_ENVIRONMENT: true })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

function pipeline(): PipelineLike {
  return { pipeline_id: 'review-1', workspace: 'original', status: 'completed', clips: [
    { index: 0, video_filename: 'new.mp4', video_prompt: '  literal\nprompt  ', video_attempts: [
      { id: 'old-id', filename: 'old.mp4' }, { id: 'new-id', filename: 'new.mp4' }] },
    { index: 1, video_filename: 'approved.mp4', tag: 'good' },
  ] }
}
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

test('mounted production review saves, reloads and exports the actual approved selection', async context => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewHost } = await import('../src/features/production-review/ProductionReviewHost')
  let saved = pipeline()
  let exported: Record<string, unknown> | null = null
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit = {}) => {
    if (url.endsWith('/review')) {
      const body = JSON.parse(String(options.body))
      assert.equal(body.workspace, 'original')
      saved = applyPersistCommands(saved, body.commands)
      return response(saved)
    }
    if (url.endsWith('/probe')) return response({ duration: 1, width: 640, height: 360, fps: 24, has_audio: true })
    if (url.endsWith('/export')) {
      exported = JSON.parse(String(options.body))
      return response({ job_id: 'export-real', status: 'completed', filename: 'selection.mp4', message: 'Ready' })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  const view = (key: string) => <ProductionReviewHost key={key} workspace="original" pipeline={saved as SavedPipelineState} />
  try {
    const root = render(view('first'))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'old-id' })))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Approve' })))
    assert.equal(saved.clips[0].selected_video_filename, 'old.mp4')
    assert.equal(saved.clips[0].tag, 'good')
    root.rerender(view('reload'))
    assert.equal(screen.getByRole('button', { name: 'old-id' }).getAttribute('aria-pressed'), 'true')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Export approved selection' })))
    assert.ok(exported)
    const body = exported as { workspace: string; clips: Array<{ name: string; source: string }> }
    assert.equal(body.workspace, 'original')
    assert.deepEqual(body.clips.map(clip => clip.name), ['old.mp4', 'approved.mp4'])
    assert.ok(body.clips.every(clip => clip.source.endsWith('workspace=original')))
    assert.match(screen.getByRole('link', { name: 'Download MP4' }).getAttribute('href') || '', /selection.mp4.*original/)
  } finally { cleanup() }
})

test('failed persistence keeps the current take and displays the error', async context => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewHost } = await import('../src/features/production-review/ProductionReviewHost')
  context.mock.method(globalThis, 'fetch', async () => response({ detail: 'Production is busy' }, 409))
  try {
    render(<ProductionReviewHost workspace="original" pipeline={pipeline() as SavedPipelineState} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'old-id' })))
    assert.equal(screen.getByRole('button', { name: 'new-id' }).getAttribute('aria-pressed'), 'true')
    assert.match(screen.getByRole('alert').textContent || '', /Production is busy/)
  } finally { cleanup() }
})

test('regeneration reads a real saved attempt and does not fabricate queued success', async context => {
  const saved = pipeline(), desk = projectReviewDesk({ pipeline: saved })
  const calls: string[] = []
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit = {}) => {
    calls.push(url)
    if (url.endsWith('/rerun-video')) {
      assert.equal(JSON.parse(String(options.body)).prompt, '  literal\nprompt  ')
      saved.clips[0].video_attempts!.push({ id: 'persisted-id', filename: 'regenerated.mp4' })
      return response({ filename: 'regenerated.mp4', clip_index: 0 })
    }
    return response(saved)
  })
  const results = await regenerateReview(desk, { productionId: desk.productionId, keepShotIds: [desk.shots[1].id], jobs: [
    { shotId: desk.shots[0].id, clipIndex: 0, prompt: '  literal\nprompt  ', refs: [], parentTakeId: 'new-id' },
  ] })
  assert.equal(calls.length, 2)
  assert.equal(results[0].take?.id, 'persisted-id')
  assert.equal(results[0].take?.filename, 'regenerated.mp4')
  assert.equal(saved.clips[1].tag, 'good')
})

test('approval belongs to the exact take, and frame counts are not guessed as seconds', () => {
  const source = pipeline()
  source.clips[0].tag = 'good'
  source.clips[0].video_attempts![0].video_length = 83
  const desk = projectReviewDesk({ pipeline: source })
  const selected = selectExactTake(desk, desk.shots[0].id, 'old-id')
  assert.equal(selected.shots[0].decision, 'pending')
  assert.equal(selected.shots[0].takes[0].durationSeconds, null)
  assert.deepEqual(exportApprovedSelection(selected).clips.map(clip => clip.filename), ['approved.mp4'])
})

test('take timing uses each attempt frame rate and never borrows planned duration', () => {
  const source = pipeline()
  source.clips[0].planned_clip = { start: 0, end: 30 }
  source.clips[0].video_attempts![0] = { id: 'old-id', filename: 'old.mp4', video_length: 48, fps: 24 }
  source.clips[0].video_attempts![1] = { id: 'new-id', filename: 'new.mp4', video_length: 120, fps: 30 }
  const project = () => projectReviewDesk({ pipeline: source }).shots[0].takes.map(take => take.durationSeconds)
  assert.deepEqual(project(), [2, 4])
  source.clips[0].video_attempts![0].fps = 0
  assert.deepEqual(project(), [null, 4])
})

test('loaded video metadata displays distinct take durations and resets on source changes', async context => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewHost } = await import('../src/features/production-review/ProductionReviewHost')
  let saved = pipeline()
  saved.clips[0].planned_clip = { start: 0, end: 30 }
  context.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit = {}) => {
    saved = applyPersistCommands(saved, JSON.parse(String(options.body)).commands)
    return response(saved)
  })
  try {
    render(<ProductionReviewHost workspace="original" pipeline={saved as SavedPipelineState} />)
    for (const [id, duration] of [['take-a', 2.5], ['take-b', 4.25]] as const) {
      const video = screen.getByTestId(id).querySelector('video')!
      Object.defineProperty(video, 'duration', { value: duration, configurable: true })
      fireEvent.loadedMetadata(video)
      assert.match(screen.getByTestId(id).textContent || '', new RegExp(`Duration ${duration.toFixed(1)}`))
    }
    const originalSource = screen.getByTestId('take-a').querySelector('video')!.getAttribute('src')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'old-id' })))
    assert.notEqual(screen.getByTestId('take-a').querySelector('video')!.getAttribute('src'), originalSource)
    assert.doesNotMatch(screen.getByTestId('take-a').textContent || '', /Duration 2\.5/)
  } finally { cleanup() }
})

test('saving in the mounted dashboard updates the selected pipeline immediately', async context => {
  const { render, screen, within, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { DirectorDashboard } = await import('../src/components/DirectorDashboard/DirectorDashboard')
  const { useStore } = await import('../src/stores/useStore')
  let saved = { ...pipeline(), video_params: {}, output_files: [] } as SavedPipelineState
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit = {}) => {
    assert.ok(url.endsWith('/review'))
    saved = applyPersistCommands(saved, JSON.parse(String(options.body)).commands) as SavedPipelineState
    return response(saved)
  })
  const previous = useStore.getState()
  useStore.setState({ activeWorkspace: 'original', dashboardOpen: true, dashboardLoading: false,
    dashboardSelectedPipeline: saved, dashboardPipelineList: [], dashboardLoadError: null })
  try {
    render(<DirectorDashboard />)
    const panel = within(screen.getByRole('region', { name: 'Production review', hidden: true }))
    await act(async () => fireEvent.click(panel.getByRole('button', { name: 'old-id', hidden: true })))
    assert.equal(useStore.getState().dashboardSelectedPipeline?.clips[0].video_filename, 'old.mp4')
    await act(async () => fireEvent.click(panel.getByRole('button', { name: 'Approve', hidden: true })))
    assert.equal(useStore.getState().dashboardSelectedPipeline?.clips.filter(clip => clip.tag === 'good').length, 2)
    await act(async () => fireEvent.click(panel.getByRole('button', { name: 'Reject', hidden: true })))
    assert.equal(useStore.getState().dashboardSelectedPipeline?.clips[0].tag, 'needs_work')
  } finally { cleanup(); useStore.setState(previous, true) }
})

test('notes blur then approve persist both decisions while the first save is in flight', async () => {
  const { render, screen, fireEvent, act, cleanup, waitFor } = await import('@testing-library/react')
  const { ProductionReviewDesk } = await import('../src/features/production-review/ProductionReviewDesk')
  let desk = projectReviewDesk({ pipeline: pipeline() })
  const saves: Array<{ commands: unknown[]; resolve: () => void }> = []
  try {
    render(<ProductionReviewDesk desk={desk} onChange={next => { desk = next }}
      onPersist={commands => new Promise<void>(resolve => { saves.push({ commands, resolve }) })} />)
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'keep the lantern' } })
    fireEvent.blur(screen.getByLabelText('Notes'))
    assert.equal(screen.getByRole('button', { name: 'Approve' }).matches(':disabled'), false,
      'blur must not disable the button before the browser dispatches its click')
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    assert.equal(saves.length, 1)
    await act(async () => { saves[0].resolve() })
    await waitFor(() => assert.equal(saves.length, 2))
    const commands = saves[1].commands as Array<{ type: string; notes?: string; tag?: string | null }>
    assert.equal(commands.find(item => item.type === 'note_clip')?.notes, 'keep the lantern')
    assert.equal(commands.find(item => item.type === 'tag_clip')?.tag, 'good')
    await act(async () => { saves[1].resolve() })
    assert.equal(desk.shots[0].notes, 'keep the lantern')
    assert.equal(desk.shots[0].decision, 'approved')
  } finally { cleanup() }
})

test('queued take selection and approval are applied in order after notes', async () => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewDesk } = await import('../src/features/production-review/ProductionReviewDesk')
  let desk = projectReviewDesk({ pipeline: pipeline() })
  const saves: Array<{ commands: unknown[]; resolve: () => void }> = []
  try {
    render(<ProductionReviewDesk desk={desk} onChange={next => { desk = next }}
      onPersist={commands => new Promise<void>(resolve => { saves.push({ commands, resolve }) })} />)
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'use the earlier take' } })
    fireEvent.blur(screen.getByLabelText('Notes'))
    fireEvent.click(screen.getByRole('button', { name: 'old-id' }))
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    assert.equal(saves.length, 1)
    await act(async () => { saves[0].resolve() })
    assert.equal(saves.length, 2)
    await act(async () => { saves[1].resolve() })
    assert.equal(saves.length, 3)
    await act(async () => { saves[2].resolve() })
    assert.equal(desk.shots[0].selectedTakeId, 'old-id')
    assert.equal(desk.shots[0].notes, 'use the earlier take')
    assert.equal(desk.shots[0].decision, 'approved')
  } finally { cleanup() }
})

test('an approval that failed to save never enters the exported selection', async () => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewDesk } = await import('../src/features/production-review/ProductionReviewDesk')
  const exported: string[][] = []
  try {
    render(<ProductionReviewDesk desk={projectReviewDesk({ pipeline: pipeline() })}
      onPersist={async () => { throw new Error('Production is busy') }}
      onExport={async selection => { exported.push(selection.clips.map(clip => clip.filename)) }} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Approve' })))
    assert.match(screen.getByRole('alert').textContent || '', /Production is busy/)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Export approved selection' })))
    assert.deepEqual(exported, [['approved.mp4']])
  } finally { cleanup() }
})

test('a saved hydrated response remains available to the next review operation', async context => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewHost } = await import('../src/features/production-review/ProductionReviewHost')
  const saved = pipeline()
  context.mock.method(globalThis, 'fetch', async () => {
    saved.clips[0].video_attempts!.push({ id: 'recovered-id', filename: 'recovered.mp4' })
    return response(saved)
  })
  try {
    render(<ProductionReviewHost workspace="original" pipeline={pipeline() as SavedPipelineState} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Approve' })))
    assert.equal(screen.queryAllByRole('button', { name: 'recovered-id' }).length, 1)
  } finally { cleanup() }
})

test('a custom comparison survives hydrated saves and parent dashboard refreshes', async context => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewHost } = await import('../src/features/production-review/ProductionReviewHost')
  let saved = pipeline()
  saved.clips[0].video_attempts!.unshift({ id: 'archive-id', filename: 'archive.mp4' })
  context.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit = {}) => {
    saved = applyPersistCommands(saved, JSON.parse(String(options.body)).commands)
    return response(saved)
  })
  function Dashboard() {
    const [source, setSource] = React.useState(saved as SavedPipelineState)
    return <ProductionReviewHost workspace="original" pipeline={source} onSaved={setSource} />
  }
  try {
    render(<Dashboard />)
    await act(async () => fireEvent.contextMenu(screen.getByRole('button', { name: 'archive-id' })))
    const compared = () => screen.getByTestId('take-b').querySelector('video')?.getAttribute('data-take-id')
    assert.equal(compared(), 'archive-id')
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'compare against archive' } })
    await act(async () => fireEvent.blur(screen.getByLabelText('Notes')))
    assert.equal(compared(), 'archive-id')
    assert.equal(saved.clips[0].review_notes, 'compare against archive')
  } finally { cleanup() }
})

test('preserving comparison choices never restores unconfirmed approval, notes or a removed take', () => {
  const previous = projectReviewDesk({ pipeline: pipeline() })
  previous.shots[0] = { ...previous.shots[0], selectedTakeId: 'old-id', approvedTakeId: 'old-id',
    decision: 'approved', notes: 'unconfirmed', compareTakeId: 'old-id' }
  const projected = projectReviewDesk({ pipeline: pipeline() })
  const restored = restoreCompareChoices(previous, projected)
  assert.equal(restored.shots[0].selectedTakeId, 'new-id')
  assert.equal(restored.shots[0].approvedTakeId, null)
  assert.equal(restored.shots[0].decision, 'pending')
  assert.equal(restored.shots[0].notes, '')
  projected.shots[0].takes = projected.shots[0].takes.filter(take => take.id !== 'old-id')
  projected.shots[0].compareTakeId = null
  assert.equal(restoreCompareChoices(previous, projected).shots[0].compareTakeId, null)
  assert.equal(restoreCompareChoices(previous, { ...projected, workspace: 'another' }).shots[0].compareTakeId, null)
})

test('a late save after leaving review cannot replace another dashboard selection', async context => {
  const { render, screen, fireEvent, act, cleanup } = await import('@testing-library/react')
  const { ProductionReviewHost } = await import('../src/features/production-review/ProductionReviewHost')
  let finish!: (value: Response) => void
  context.mock.method(globalThis, 'fetch', () => new Promise<Response>(resolve => { finish = resolve }))
  const notified: string[] = []
  try {
    const root = render(<ProductionReviewHost workspace="original" pipeline={pipeline() as SavedPipelineState}
      onSaved={saved => { notified.push(saved.pipeline_id) }} />)
    fireEvent.click(screen.getByRole('button', { name: 'old-id' }))
    root.unmount()
    await act(async () => { finish(response(pipeline())) })
    assert.deepEqual(notified, [])
  } finally { cleanup() }
})
