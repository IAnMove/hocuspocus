import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { PipelineLike, RegenPlan, ReviewDesk, TakeRecord } from '../src/features/production-review/types.ts'
import { projectReviewDesk } from '../src/features/production-review/project.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React,
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  HTMLVideoElement: dom.window.HTMLVideoElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

function fixture(): { desk: ReviewDesk; pipeline: PipelineLike; records: TakeRecord[] } {
  const pipeline: PipelineLike = {
    pipeline_id: 'pipe-1',
    production_id: 'prod-1',
    workspace: 'film',
    scene_description: 'Night watch',
    status: 'completed',
    clips: [1, 2].map(n => ({
      index: n - 1,
      shot_id: `shot-${n}`,
      duration_seconds: 4,
      video_filename: `s${n}b.mp4`,
      selected_video_filename: `s${n}b.mp4`,
      video_attempts: [
        { id: `s${n}a.mp4`, filename: `s${n}a.mp4` },
        { id: `s${n}b.mp4`, filename: `s${n}b.mp4` },
      ],
      h3_references: { image_references: [`hero-${n}.png`] },
      video_prompt: `prompt ${n}`,
    })),
  }
  const records: TakeRecord[] = [
    { generation_id: 'gen-1a', production_id: 'prod-1', status: 'completed', location: { filename: 's1a.mp4' }, timestamps: { duration_ms: 4000 } },
    { generation_id: 'gen-1b', production_id: 'prod-1', status: 'completed', location: { filename: 's1b.mp4' }, timestamps: { duration_ms: 4100 } },
    { generation_id: 'gen-2a', production_id: 'prod-1', status: 'completed', location: { filename: 's2a.mp4' } },
    { generation_id: 'gen-2b', production_id: 'prod-1', status: 'completed', location: { filename: 's2b.mp4' } },
  ]
  return { pipeline, records, desk: projectReviewDesk({ pipeline, records }) }
}

test('review desk compares A/B takes, records notes, and keeps the older id after refresh', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup, act } = await import('@testing-library/react')
  const { ProductionReviewDesk } = await import('../src/features/production-review/ProductionReviewDesk.tsx')
  const { refreshReviewDesk } = await import('../src/features/production-review/project.ts')
  const { applyPersistCommands, persistCommandsFor } = await import('../src/features/production-review/index.ts')
  const pack = fixture()
  let desk = pack.desk
  const persist: unknown[] = []
  const view = () => (
    <ProductionReviewDesk
      desk={desk}
      onChange={next => { desk = next }}
      onPersist={commands => { persist.push(...commands) }}
      activityTarget={{ kind: 'production', metadata: { production_id: 'prod-1' } }}
      fileUrl={name => `/media/${name}`}
    />
  )
  try {
    const rendered = render(view())
    assert.ok(screen.getByRole('region', { name: 'Production review' }))
    assert.ok(screen.getByText(/Opened from Activity/))
    assert.ok(screen.getByTestId('take-a'))
    assert.ok(screen.getByTestId('take-b'))
    assert.ok(screen.getAllByText(/Duration 4/).length > 0)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'gen-1a' })))
    assert.equal(desk.shots[0].selectedTakeId, 'gen-1a')
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'keep the lantern' } })
    await act(async () => fireEvent.blur(screen.getByLabelText('Notes')))
    assert.equal(desk.shots[0].notes, 'keep the lantern')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Approve' })))
    assert.equal(desk.shots[0].decision, 'approved')
    const saved = applyPersistCommands(pack.pipeline, persistCommandsFor(desk))
    desk = refreshReviewDesk(desk, saved, pack.records)
    rendered.rerender(view())
    assert.equal(screen.getByRole('button', { name: 'gen-1a' }).getAttribute('aria-pressed'), 'true')
    assert.equal(desk.shots[0].selectedTakeId, 'gen-1a')
  } finally {
    cleanup()
  }
})

test('regenerate asks for confirmation and export reports approved takes only', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { ProductionReviewDesk } = await import('../src/features/production-review/ProductionReviewDesk.tsx')
  const pack = fixture()
  let desk = pack.desk
  const plans: RegenPlan[] = []
  try {
    render(
      <ProductionReviewDesk
        desk={desk}
        onChange={next => { desk = next }}
        onPersist={async () => undefined}
        onExport={async () => undefined}
        onRegenerate={async plan => {
          plans.push(plan)
          // Exercise the pending state too: comparing an HTMLElement to null
          // here made Node format the whole React DOM graph and exhaust its heap.
          await new Promise(resolve => setTimeout(resolve, 30))
          return [
            { shotId: plan.jobs[0].shotId, ok: true, take: { id: 'gen-1c', generationId: 'gen-1c', filename: 's1c.mp4', status: 'completed', durationSeconds: 4, notes: '', refs: plan.jobs[0].refs } },
          ]
        }}
      />,
    )
    fireEvent.click(screen.getByLabelText('Shot 1'))
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate selected' }))
    assert.ok(screen.getByRole('dialog', { name: 'Regenerate a subset?' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm regenerate' }))
    await waitFor(() => assert.equal(plans.length, 1))
    await waitFor(() => assert.equal(screen.queryByText('Saving or processing…') === null, true))
    assert.equal(plans[0].jobs[0].refs.includes('hero-1.png'), true)
    fireEvent.click(screen.getByRole('button', { name: 'Export approved selection' }))
    await waitFor(() => assert.match(screen.getByRole('status').textContent || '', /No approved|Export/))
  } finally {
    cleanup()
  }
})
