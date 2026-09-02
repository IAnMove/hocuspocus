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
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: () => undefined,
  })
  dom.window.requestAnimationFrame = callback => {
    callback(0)
    return 1
  }
  dom.window.cancelAnimationFrame = () => undefined
}

installDom()

test('Runs and collection Workspaces are distinct tabs', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ mediaFilter: 'all', outputSearchQuery: '' })
  try {
    render(<TabFilter />)
    assert.ok(screen.getByRole('tab', { name: /^Runs/ }))
    assert.ok(screen.getByRole('tab', { name: /Workspaces/ }))
    assert.ok(screen.getByRole('tab', { name: /Story Lab/ }))
    assert.ok(screen.getByRole('tab', { name: /Series Lab/ }))
  } finally {
    cleanup()
  }
})

test('Runs processing lists planned shots, models and a video placeholder', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { RunsPanel } = await import('../src/features/workspaces/WorkspacesPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({
    dashboardLoading: false,
    dashboardLoadError: null,
    dashboardPipelineTotal: 12,
    dashboardPipelineList: [{
      id: 'song-1',
      status: 'failed',
      pipeline_type: 'music_video',
      created_at: 1,
      clip_count: 2,
      output_count: 0,
      scene_description: 'La Canción de Gandalf',
      workspace: 'default',
      error: 'Shot 9: silent visual field still contains affirmative vocal cues: habla',
    }],
    dashboardSelectedPipeline: {
      version: 1,
      pipeline_id: 'song-1',
      created_at: 1,
      completed_at: null,
      status: 'failed',
      phase: 'planning',
      error: 'Shot 9: silent visual field still contains affirmative vocal cues: habla',
      pipeline_type: 'music_video',
      scene_description: 'La Canción de Gandalf',
      reference_image_path: null,
      auto_mode: true,
      seamless: true,
      image_model: 'minimax:image-01',
      video_model: 'minimax_h3_legacy',
      llm_log: null,
      queue_source: 'planned',
      clips: [{
        index: 0,
        planned_clip: { duration_sec: 5.875 },
        image_prompt: '',
        video_prompt: 'Gandalf mantiene la boca cerrada y nunca habla.',
        keyframe_prompts: [],
        window_prompts: [],
        window_count: 1,
        image_prompt_pre_polish: null,
        video_prompt_pre_polish: null,
        window_prompts_pre_polish: null,
        keyframe_prompts_pre_polish: null,
        start_image_filename: null,
        keyframe_filenames: [],
        video_filename: null,
        tag: null,
        image_gen_time_sec: null,
        video_gen_time_sec: null,
        duration_seconds: 5.875,
        _director_h3_prompt_mode: 't2va',
        _director_audio_plan: { mode: 'music_driven', timing_anchor: 'audio' },
      }],
      output_files: [],
      total_time_sec: 1,
    },
    loadPipelineList: async () => undefined,
    loadMorePipelineList: async () => undefined,
    loadSavedPipeline: async () => undefined,
    retryDashboardLoad: async () => undefined,
    resumePipeline: async () => undefined,
    rejoinPipelineClips: async () => undefined,
    updateClipPrompt: async () => undefined,
    selectClipVideo: async () => undefined,
    rerunClipVideo: async () => undefined,
  })

  try {
    render(<RunsPanel />)
    assert.ok(screen.getByRole('region', { name: 'Production runs' }))
    assert.ok(screen.getByRole('navigation', { name: 'Saved production runs' }))
    assert.ok(screen.getByRole('button', { name: /Nuevo → viejo/ }))
    assert.ok(screen.getByPlaceholderText('Buscar run…'))
    assert.match(screen.getByRole('heading', { name: 'La Canción de Gandalf' }).textContent || '', /Gandalf/)
    assert.ok(screen.getAllByText(/minimax_h3_legacy/).length >= 1)
    assert.ok(screen.getByText('Gandalf mantiene la boca cerrada y nunca habla.'))
    assert.ok(screen.getByRole('button', { name: 'mute' }))
    assert.ok(screen.getByText('Video placeholder'))
    assert.ok(screen.getByRole('button', { name: /Start \/ resume videos/ }))
    assert.ok(screen.getByRole('button', { name: /Regenerar vídeo completo/ }))
    assert.ok(screen.getByRole('button', { name: 'Select all' }))
    assert.ok(screen.getByRole('button', { name: /Proponer en seleccionados/ }))
    assert.ok(screen.getByPlaceholderText(/quita todos los MC/))
    assert.ok(screen.getByText(/Queue from planned prompts/))
    assert.ok(screen.getByRole('button', { name: /Más runs \(1\/12\)/ }))
  } finally {
    cleanup()
  }
})

test('Runs hydrates a failed song attempt from planned prompts', async () => {
  const { hydratePipelineQueue } = await import('../src/features/workspaces/queue.ts')
  const hydrated = hydratePipelineQueue({
    version: 1,
    pipeline_id: '3fa9b7d7',
    created_at: 1,
    completed_at: null,
    status: 'failed',
    pipeline_type: 'music_video',
    scene_description: 'La Canción de Gandalf',
    reference_image_path: null,
    auto_mode: true,
    seamless: true,
    image_model: 'minimax:image-01',
    video_model: 'minimax_h3_legacy',
    llm_log: null,
    clips: [],
    planned_clips: [{
      _director_h3_source_prompt: 'Gandalf mantiene la boca cerrada y nunca habla.',
      duration_sec: 5.875,
      _director_audio_plan: { mode: 'music_driven' },
    }],
    output_files: [],
    total_time_sec: 1,
  })
  assert.equal(hydrated.queue_source, 'planned')
  assert.equal(hydrated.clips.length, 1)
  assert.equal(hydrated.clips[0].video_prompt, 'Gandalf mantiene la boca cerrada y nunca habla.')
  assert.equal(hydrated.clips[0].duration_seconds, 5.875)
})
