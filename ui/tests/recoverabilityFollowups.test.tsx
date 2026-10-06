import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

type FetchCall = { url: string; init?: RequestInit }

function mockFetch(reply: (url: string, init?: RequestInit) => unknown): { calls: FetchCall[]; restore: () => void } {
  const original = globalThis.fetch
  const calls: FetchCall[] = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    const body = reply(url, init)
    return new Response(JSON.stringify(body ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  return { calls, restore: () => { globalThis.fetch = original } }
}

test('a Wizard report names the kits, stories, episodes and Video 3D results it changed', async () => {
  const { wizardTrailTargets } = await import('../src/features/agent/wizardTrail.ts')
  assert.deepEqual(wizardTrailTargets({ state: 'completed', target: { kind: 'character_kit', id: 'rayo', title: 'Rayo' } }),
    [{ kind: 'character_kit', id: 'rayo', title: 'Rayo' }])
  assert.deepEqual(wizardTrailTargets({
    state: 'completed', target: { kind: 'story_song', id: 'cue-1', title: 'Tema' }, projectTarget: { kind: 'story', id: 'story-1', title: 'El faro' },
  }), [{ kind: 'story', id: 'story-1', title: 'El faro' }])
  assert.deepEqual(wizardTrailTargets({
    state: 'completed', target: { kind: 'video_3d_scene', id: 'w3d-0123456789ab', title: 'anime-face-off' },
    metadata: { result: { template: { id: 'user-duelo', title: 'Duelo' }, scene: { file: 'Duelo-w3d-0123456789ab-x.world3d.scene.json' } } },
  }).map(target => target.kind), ['world3d_scene', 'world3d_template', 'scene_file'])
  assert.deepEqual(wizardTrailTargets({ state: 'completed', target: { kind: 'studio_form', id: 'image', title: 'Image' } }), [])
  assert.deepEqual(wizardTrailTargets({ state: 'failed', target: { kind: 'character_kit', id: 'rayo', title: 'Rayo' } }), [])
})

test('a Wizard change is reported once with its series, and never fails the Wizard', async () => {
  const { reportWizardChange } = await import('../src/features/agent/wizardTrail.ts')
  const { useSeriesStore } = await import('../src/features/series/store.ts')
  const library = useSeriesStore.getState().library
  useSeriesStore.setState({ library: { ...library, seriesById: { 'pu-es': { id: 'pu-es', episodesById: { ep1: { id: 'ep1' } } } } } as never })
  const fetched = mockFetch(() => ({ recorded: true }))
  try {
    const report = { state: 'completed' as const, target: { kind: 'series_episode', id: 'ep1', title: 'Plus Ultra · 1' } }
    assert.equal(await reportWizardChange({ workspace: 'pu', capability: 'update_series_episode', commandId: 'c1', risk: 'edit', report }), true)
    assert.equal(await reportWizardChange({ workspace: 'pu', capability: 'open_series_section', commandId: 'c2', risk: 'read', report }), false)
    assert.equal(fetched.calls.length, 1)
    assert.equal(fetched.calls[0].url, '/api/v1/tasks/wizard-changes')
    assert.deepEqual(JSON.parse(String(fetched.calls[0].init?.body)), {
      workspace: 'pu', capability: 'update_series_episode', commandId: 'c1',
      targets: [{ kind: 'series_episode', id: 'ep1', title: 'Plus Ultra · 1', series: 'pu-es' }],
    })
  } finally {
    fetched.restore()
  }
  const failing = mockFetch(() => { throw new Error('offline') })
  try {
    assert.equal(await reportWizardChange({ workspace: 'pu', capability: 'create_character_kit', commandId: 'c3', risk: 'edit',
      report: { state: 'completed', target: { kind: 'character_kit', id: 'ines', title: 'Inés' } } }), false)
  } finally {
    failing.restore()
  }
})

test('a Wizard trail row is badged Wizard though it is an agent change row', async () => {
  const { taskOrigin, isAgentChange, agentTargets } = await import('../src/features/activity/agentOrigin.ts')
  const row = {
    id: 'task-wizard-1', root_id: 'task-wizard-1', kind: 'agent', title: 'Wizard · El faro', workflow: 'create_story', status: 'completed',
    phase: 'completed', message: 'create_story', created_at: 1, updated_at: 2, attempt: 1, max_attempts: 1,
    metadata: { adapter: 'agent', actor: 'wizard', tool: 'wizard', capability: 'create_story', targets: [{ kind: 'story', id: 'story-1', title: 'El faro' }] },
  }
  assert.equal(taskOrigin(row as never), 'wizard')
  assert.equal(isAgentChange(row as never), true)
  assert.deepEqual(agentTargets(row as never), [{ kind: 'story', id: 'story-1', title: 'El faro' }])
})

test('gallery provenance names the agent, the music style, the voice and what a tool made it from', async () => {
  const { outputProvenance, outputMaker } = await import('../src/lib/outputProvenance.ts')
  assert.deepEqual(outputMaker({ origin: { tool: 'external_agent', actor: 'user', capability: 'generation.image' } }),
    { origin: 'agent', capability: 'generation.image' })
  assert.deepEqual(outputMaker({ origin: { tool: 'world3d-export', actor: 'user' }, requested_by: { tool: 'external_agent', capability: 'scenes.world3d.export' } }),
    { origin: 'agent', capability: 'scenes.world3d.export' })
  assert.deepEqual(outputMaker({ origin: { tool: 'wizard', actor: 'wizard', capability: 'generation.speech' } }), { origin: 'wizard', capability: 'generation.speech' })
  assert.equal(outputMaker({ origin: { tool: 'studio', actor: 'user' } }), null)
  const music = outputProvenance({ params: { model_type: 'ace_step_v1_5', _audio_sub_mode: 'music', alt_prompt: 'Epic anime battle, drums', prompt: '[Instrumental]' } })
  assert.equal(music.style, 'Epic anime battle, drums')
  assert.equal(music.voice, '')
  const designed = outputProvenance({ params: { model_type: 'qwen3_tts_voicedesign', _audio_sub_mode: 'speech', alt_prompt: 'Hoarse tired man', model_mode: 'spanish' } })
  assert.deepEqual([designed.voice, designed.language, designed.style], ['Hoarse tired man', 'spanish', ''])
  const cloned = outputProvenance({ params: { model_type: 'qwen3_tts_base', _audio_sub_mode: 'speech', audio_guide: '/x/outputs/pu/ines-voice.wav', alt_prompt: 'transcript', model_mode: 'spanish' } })
  assert.deepEqual([cloned.voiceReference, cloned.voice], ['ines-voice.wav', ''])
  const keyed = outputProvenance({
    params: { tool: 'studio.key', mode: 'green', scene_file: 'Duelo-x.world3d.scene.json', video_editor: { montage: { file: 'cierre.montage.json', revision: 2 } } },
    lineage: { parents: [{ id: 'a', kind: 'image', uri: 'plate.png', role: 'source' }] },
  })
  assert.deepEqual([keyed.tool, keyed.parents, keyed.sceneFile, keyed.montageFile], ['studio.key', ['plate.png'], 'Duelo-x.world3d.scene.json', 'cierre.montage.json'])
})

test('the details panel shows who made a file and its voice', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ImagePreviewInformation } = await import('../src/components/common/ImagePreviewMetadata.tsx')
  try {
    render(<ImagePreviewInformation image={{ name: 'ln-1.wav', url: '/api/v1/file/ln-1.wav' } as never} dimensions="" duration="" onRetry={() => undefined}
      info={{ done: true, metadata: { source: 'sidecar', params: { model_type: 'qwen3_tts_voicedesign', _audio_sub_mode: 'speech', prompt: '¡A babor!', alt_prompt: 'Old captain, hoarse', model_mode: 'spanish' },
        origin: { tool: 'external_agent', actor: 'agent', capability: 'generation.speech' } } as never }} />)
    const provenance = document.querySelector('[data-testid="output-provenance"]')
    assert.ok(provenance)
    assert.ok(document.querySelector('[data-origin="agent"]'))
    assert.ok(screen.getByText('An agent (MCP) · generation.speech'))
    assert.ok(screen.getByText('Old captain, hoarse'))
    assert.ok(screen.getByText('spanish'))
  } finally {
    cleanup()
  }
})

test('scene titles drop the revision ids saves append', async () => {
  const { sceneLibraryTitle, sceneOutputMatchesName } = await import('../src/lib/sceneLibrary.ts')
  assert.equal(sceneLibraryTitle('Anime-Face-off-w3d-0123456789ab-0f1e2d3c4b5a69788796a5b4c3d2e1f0.world3d.scene.json'), 'Anime Face off w3d 0123456789ab')
  assert.equal(sceneLibraryTitle('confesion-e1s04-79fa96aedc.scene.json'), 'confesion e1s04')
  assert.equal(sceneLibraryTitle('2026-10-06-17h59m40s_Intro_abc123.scene.json'), 'Intro')
  assert.ok(sceneOutputMatchesName({ name: 'confesion-e1s04-79fa96aedc.scene.json' }, 'confesion e1s04'))
})

test('a working scene is an Open dialog item with its own title', async () => {
  const { workingSceneItem } = await import('../src/features/scene3d/workingScenes.ts')
  const { outputToPickerItem } = await import('../src/features/asset-picker/adapters.ts')
  const item = workingSceneItem({ sceneId: 'w3d-0123456789ab', revision: 4, templateId: 'anime-face-off', title: 'Anime · Face-off', updatedAt: 100 },
    'Anime · Face-off · working scene, not published (revision 4)')
  assert.equal(item.url, 'working-scene:w3d-0123456789ab')
  assert.equal(outputToPickerItem(item, 'pu').title, 'Anime · Face-off · working scene, not published (revision 4)')
})

test('the production list shows steps and chapters and resumes a stopped production', async () => {
  const { render, screen, cleanup, fireEvent, waitFor } = await import('@testing-library/react')
  const { SeriesProduceJobs } = await import('../src/features/series/SeriesProduceJobs.tsx')
  const job = {
    jobId: 'produce-1', seriesId: 'pu', episodeId: 'ep1', status: 'failed', createdAt: 1_790_000_000, languages: ['spanish', 'english'],
    message: 'Render english failed; resume to retry',
    steps: [{ kind: 'render', language: 'spanish', status: 'done' }, { kind: 'render', language: 'english', status: 'failed', error: 'no voice' },
      { kind: 'assemble', language: 'spanish', status: 'done' }],
    chapters: { spanish: { file: 'cap-es.mp4', subtitledFile: 'cap-es.subtitled.mp4' } },
  }
  const fetched = mockFetch((url, init) => (init?.method === 'POST' ? { ...job, status: 'queued', message: 'Resuming' } : { jobs: [job], total: 1 }))
  try {
    render(<SeriesProduceJobs workspace="pu" series={{ id: 'pu' } as never} episode={{ id: 'ep1' } as never} />)
    await waitFor(() => assert.ok(document.querySelector('[data-testid="series-production-produce-1"]')))
    assert.ok(fetched.calls[0].url.includes('/api/v1/series/produce/jobs?workspace=pu&series_id=pu&episode_id=ep1'))
    assert.ok(screen.getByText(/no voice/))
    assert.ok(screen.getByText('Chapter spanish with subtitles'))
    fireEvent.click(screen.getByText('Resume'))
    await waitFor(() => assert.ok(screen.getByText('Resuming')))
    const resume = fetched.calls.find(call => call.init?.method === 'POST')
    assert.equal(resume?.url, '/api/v1/series/produce/jobs/produce-1/resume')
    assert.deepEqual(JSON.parse(String(resume?.init?.body)), { workspace: 'pu' })
  } finally {
    cleanup()
    fetched.restore()
  }
})
