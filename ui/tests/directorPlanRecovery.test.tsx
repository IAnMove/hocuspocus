import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { DirectorV2PlanJob } from '../src/types'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function recoverableJob(overrides: Partial<DirectorV2PlanJob> = {}): DirectorV2PlanJob {
  return {
    jobId: 'director-plan-recovery',
    workspace: 'default',
    skillType: 'music_video',
    status: 'failed',
    phase: 'failed',
    message: 'Completed batches are recoverable',
    total: 41,
    completedIndices: Array.from({ length: 24 }, (_, index) => index + 1),
    missingIndices: Array.from({ length: 17 }, (_, index) => index + 25),
    completedBatches: [
      { indices: Array.from({ length: 8 }, (_, index) => index + 1), completedAt: 1 },
    ],
    activeBatch: [],
    calls: 3,
    usage: { total_tokens: 12345, calls: 3 },
    error: 'Provider stopped during the final batch',
    result: null,
    createdAt: 1,
    updatedAt: 2,
    finishedAt: 2,
    ...overrides,
  }
}

test('partial-plan card explains saved work and resumes only missing clips', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { DirectorPlanRecoveryCard } = await import('../src/components/Sidebar/DirectorPlanRecoveryCard.tsx')
  let resumed = 0
  try {
    render(
      <DirectorPlanRecoveryCard
        job={recoverableJob()}
        loading={false}
        onResume={() => { resumed += 1 }}
      />,
    )
    assert.ok(screen.getByRole('heading', { name: 'Propuesta parcial recuperable' }))
    assert.match(screen.getByText(/24 de 41 clips/).textContent || '', /No se ha iniciado ninguna generación de imágenes/)
    assert.equal(screen.getByText('Clips 25–41').textContent, 'Clips 25–41')
    assert.equal(screen.getByText('12,345').textContent, '12,345')
    fireEvent.click(screen.getByRole('button', { name: 'Reanudar clips faltantes' }))
    assert.equal(resumed, 1)
  } finally {
    cleanup()
  }
})

test('resume keeps rendering gated on failure, then publishes the complete plan', { concurrency: false }, async t => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const originalConsoleError = console.error
  let requestCount = 0
  let imageGenerationStarts = 0
  t.after(() => {
    globalThis.fetch = originalFetch
    console.error = originalConsoleError
  })
  console.error = () => undefined
  globalThis.fetch = async input => {
    const url = String(input)
    assert.match(url, /director-plan-recovery\/resume\?workspace=default$/)
    requestCount += 1
    if (requestCount === 1) {
      const job = recoverableJob({ missingIndices: [41], error: 'Last clip failed again' })
      return new Response(JSON.stringify({
        detail: {
          code: 'director_plan_incomplete',
          message: 'Last clip failed again',
          job,
          resume: {
            action: 'resume_missing',
            method: 'POST',
            path: '/api/v1/director/v2/plan/jobs/director-plan-recovery/resume?workspace=default',
          },
          imagesQueued: false,
        },
      }), { status: 500, headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({
      clip_plans: [{ image_prompt: 'Complete still', video_prompt: 'Complete motion' }],
      production_plan: { skill_type: 'music_video', shots: [] },
      skill_type: 'music_video',
      plan_job_id: 'director-plan-recovery',
    }), { headers: { 'content-type': 'application/json' } })
  }

  useStore.setState({
    activeWorkspace: 'default',
    activities: {},
    directorAutoMode: true,
    directorPlanRecovery: recoverableJob(),
    directorClipPlans: [],
    directorError: null,
    directorStep: 'style',
    upsertActivity: () => undefined,
    removeActivity: () => undefined,
    directorGenerateStartImages: async () => { imageGenerationStarts += 1 },
  })

  await useStore.getState().directorResumePlan()
  assert.equal(imageGenerationStarts, 0)
  assert.deepEqual(useStore.getState().directorPlanRecovery?.missingIndices, [41])
  assert.equal(useStore.getState().directorClipPlans.length, 0)

  await useStore.getState().directorResumePlan()
  assert.equal(imageGenerationStarts, 1)
  assert.equal(useStore.getState().directorPlanRecovery, null)
  assert.equal(useStore.getState().directorClipPlans[0]?.image_prompt, 'Complete still')
  assert.equal(useStore.getState().directorStep, 'review')
})
