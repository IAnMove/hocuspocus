import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/',
  })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
  return dom
}

installDom()

function makeSeriesReviewFixture() {
  const referenceManifest = {
    strategy: 'direct', selected: [], omitted: [], warnings: [], errors: [],
    firstFrameRole: 'none', capabilitySnapshot: {},
  }
  const attempt = (id: string, assetId: string) => ({
    id, status: 'completed', prompt: `Prompt ${id}`, negativePrompt: '', model: 'minimax_h3',
    referenceManifest, seed: 42, settings: {}, startTimeSeconds: 0, endTimeSeconds: 5,
    createdAt: '2026-08-16T00:00:00Z', completedAt: '2026-08-16T00:00:05Z',
    elapsedMs: 5000, outputAssetIds: [assetId], retryCount: 0,
  })
  const shot = (id: string, order: number, attemptId: string, assetId: string) => ({
    id, sceneId: 'scene-1', order, durationSeconds: 5, framing: 'wide', camera: 'locked',
    action: `Action ${order}`, dialogueBeats: [], visibleCharacterIds: [], speakingCharacterIds: [],
    wardrobeByCharacterId: {}, propIds: [], emotionalStateByCharacterId: {}, renderStrategy: 'direct',
    referencePolicy: { mode: 'automatic', manualIncludeAssetIds: [], manualExcludeAssetIds: [] },
    prompt: `Shot ${order}`, negativePrompt: '', attempts: [attempt(attemptId, assetId)],
  })
  const episode = {
    id: 'episode-1', title: 'Episode 1', shots: [
      shot('shot-1', 1, 'attempt-1', 'asset-1'),
      shot('shot-2', 2, 'attempt-2', 'asset-2'),
    ],
    proposedCanonDelta: { baseRevision: 1, sourceEpisodeId: 'episode-1', add: [], change: [], retire: [] },
  }
  const asset = (id: string, filename: string) => ({
    id, workspaceId: 'default', kind: 'video', uri: `outputs/${filename}`,
    ownerType: 'attempt', ownerId: id, isDerivedThumbnail: false, metadata: {},
  })
  const series = {
    id: 'series-1', title: 'Series', assets: {
      'asset-1': asset('asset-1', 'clip-1.mp4'),
      'asset-2': asset('asset-2', 'clip-2.mp4'),
    },
    provider: { videoSettings: { resolution: '540p', orientation: 'landscape' } },
  }
  return { episode, series }
}

test('Director recovery resumes the selected crashed pipeline from the accessible control', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { DirectorDashboard } = await import('../src/components/DirectorDashboard/DirectorDashboard.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const pipeline = {
    version: 1, pipeline_id: 'director-crashed-1', created_at: 1, completed_at: null,
    status: 'crashed', pipeline_type: 'music_video', scene_description: 'Rainy recovery',
    reference_image_path: null, auto_mode: true, seamless: false, image_model: 'flux',
    video_model: 'wan', llm_log: null, clips: [], output_files: [], total_time_sec: 12,
  }
  let resumedPipeline = ''
  useStore.setState({
    dashboardOpen: true,
    dashboardLoading: false,
    dashboardPipelineList: [{
      id: pipeline.pipeline_id, status: pipeline.status, pipeline_type: pipeline.pipeline_type,
      created_at: pipeline.created_at, clip_count: 0, output_count: 0,
      scene_description: pipeline.scene_description, workspace: 'default',
    }],
    dashboardSelectedPipeline: pipeline,
    resumePipeline: async pipelineId => { resumedPipeline = pipelineId },
  })

  render(<DirectorDashboard />)
  fireEvent.click(screen.getByRole('button', { name: /^Resume$/ }))
  await waitFor(() => assert.equal(resumedPipeline, pipeline.pipeline_id))
  useStore.setState({ dashboardOpen: false, dashboardSelectedPipeline: null })
  cleanup()
})

test('Approve all sends every eligible shot in one bulk review action', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesReviewPanel } = await import('../src/features/series/SeriesReviewPanel.tsx')
  const { episode, series } = makeSeriesReviewFixture()
  let submitted: { selections?: Array<{ shotId: string; attemptId: string }> } | null = null
  let reloads = 0
  globalThis.fetch = async (_input: string | URL | Request, init?: RequestInit) => {
    submitted = JSON.parse(String(init?.body || '{}'))
    return new Response('{}', { headers: { 'content-type': 'application/json' } })
  }

  render(<SeriesReviewPanel
    workspace="default"
    series={series}
    episode={episode}
    job={null}
    setJob={() => {}}
    reload={async () => { reloads += 1 }}
    startRender={async () => {}}
    updateEpisode={() => {}}
    saveNow={async () => null}
  />)
  fireEvent.click(screen.getByRole('button', { name: 'Approve all (2)' }))
  await waitFor(() => assert.equal(reloads, 1))
  assert.deepEqual(submitted?.selections, [
    { shotId: 'shot-1', attemptId: 'attempt-1' },
    { shotId: 'shot-2', attemptId: 'attempt-2' },
  ])
  cleanup()
})

test('Play all advances through ordered shot slots and stops after the final clip', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesReviewPanel } = await import('../src/features/series/SeriesReviewPanel.tsx')
  const { episode, series } = makeSeriesReviewFixture()
  let playCalls = 0
  Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: async () => { playCalls += 1 },
  })

  render(<SeriesReviewPanel
    workspace="default"
    series={series}
    episode={episode}
    job={null}
    setJob={() => {}}
    reload={async () => {}}
    startRender={async () => {}}
    updateEpisode={() => {}}
    saveNow={async () => null}
  />)
  fireEvent.click(screen.getByRole('button', { name: 'Play all' }))
  await screen.findByText('Shot 1 · 1/2')
  fireEvent.ended(document.querySelector('video') as HTMLVideoElement)
  await screen.findByText('Shot 2 · 2/2')
  fireEvent.ended(document.querySelector('video') as HTMLVideoElement)
  await waitFor(() => assert.equal(screen.queryByRole('button', { name: 'Stop' }), null))
  assert.ok(playCalls >= 2)
  cleanup()
})

test('recovery dialog resumes the durable queue through its accessible button', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { QueueRecoveryDialog } = await import('../src/components/QueueRecoveryDialog.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  let reconnects = 0
  useStore.setState({ reconnectJobs: async () => { reconnects += 1 } })
  globalThis.fetch = async () => new Response(JSON.stringify({
    jobs: [{
      job_id: 'job-1', model_type: 'minimax_h3', previous_status: 'running',
      prompt_preview: 'A cyclist crosses the rain', workspace: 'default',
    }],
  }), { headers: { 'content-type': 'application/json' } })

  render(<QueueRecoveryDialog />)
  await screen.findByRole('dialog', { name: /cola de generación por recuperar/i })
  const resume = screen.getByRole('button', { name: 'Retomar cola' })
  assert.equal(resume.disabled, false)
  resume.click()
  await waitFor(() => assert.equal(reconnects, 1))
  await waitFor(() => assert.equal(screen.queryByRole('dialog'), null))
  cleanup()
})

test('episode proposal review exposes editable controls and applies the edited draft', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesEpisodeProposalReview } = await import('../src/features/series/SeriesEpisodeProposalReview.tsx')
  const scene = {
    id: 'scene-1', purpose: 'Arrival', entryState: 'Outside', exitState: 'Inside',
    locationId: 'location-1', time: 'Day', beats: [], dialogue: [],
  }
  const shot = {
    id: 'shot-1', sceneId: scene.id, locationId: scene.locationId, order: 1,
    durationSeconds: 5, framing: 'wide', camera: 'locked', action: 'Arrives',
    prompt: 'A person arrives', negativePrompt: '', audioDirection: '',
    visibleCharacterIds: [], dialogueBeats: [], renderStrategy: 'direct',
    attempts: [], approvedAttemptId: null,
  }
  const episode = {
    id: 'episode-1', title: 'Episode 1', revision: 1,
    outline: { beats: ['Arrival'] }, script: [scene], shots: [shot],
    proposedCanonDelta: { baseRevision: 1, add: [], change: [], retire: [] },
  }
  const series = {
    id: 'series-1', title: 'Series', locations: [{ id: 'location-1', name: 'Street' }],
    characters: [], assets: {}, provider: { videoSettings: { resolution: '540p', orientation: 'landscape' } },
  }
  let applied: typeof episode | null = null
  render(<SeriesEpisodeProposalReview
    currentEpisode={episode}
    proposal={episode}
    series={series}
    busy={false}
    onApply={async draft => { applied = draft }}
  />)
  fireEvent.click(screen.getByRole('button', { name: 'Add beat' }))
  assert.equal(screen.getByText('Manual edits pending').textContent, 'Manual edits pending')
  fireEvent.click(screen.getByRole('button', { name: /Apply reviewed/ }))
  assert.equal(applied?.outline.beats.length, 2)
  cleanup()
})
