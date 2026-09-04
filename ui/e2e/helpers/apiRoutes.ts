import type { Page } from '@playwright/test'

export const RUNTIME_IDENTITY = {
  instance_id: 'e2e-instance',
  ui_build_id: 'e2e-ui-build',
} as const

type Json = Record<string, unknown> | unknown[]

export interface ApiRouteSession {
  unhandled: Array<{ method: string; url: string }>
}

export type BackgroundRemovalE2EMode = 'complete' | 'cancel' | 'fail'
export type UpscaleE2EMode = 'complete' | 'cancel' | 'fail'

export interface ApiRouteOptions {
  backgroundRemovalMode?: BackgroundRemovalE2EMode
  upscaleMode?: UpscaleE2EMode
}

const SYSTEM_STATS = {
  cpu: { percent: 1 },
  ram: { percent: 10, used_gb: 4, total_gb: 32 },
  gpu: {
    available: false,
    percent: 0,
    vram_used_gb: 0,
    vram_total_gb: 0,
    vram_percent: 0,
  },
  model: { name: null, model_type: null, loaded: false },
  runtime: RUNTIME_IDENTITY,
}

const SERVICES_CONFIG = {
  llm_model_id: '',
  llm_device: 'cpu',
  llm_provider: 'local',
  llm_remote_url: '',
  enhance_llm_model_id: '',
  enhance_llm_device: 'cpu',
  google_api_key: '',
  google_api_key_set: false,
  openai_api_key: '',
  openai_api_key_set: false,
  deepseek_api_key: '',
  deepseek_api_key_set: false,
  compatible_api_key: '',
  compatible_api_key_set: false,
  compatible_base_url: '',
  anthropic_api_key: '',
  anthropic_api_key_set: false,
  minimax_api_key: '',
  minimax_api_key_set: false,
  minimax_llm_api_key: '',
  minimax_llm_api_key_set: false,
  minimax_image_api_key: '',
  minimax_image_api_key_set: false,
  minimax_music_api_key: '',
  minimax_music_api_key_set: false,
  grok_api_key: '',
  grok_api_key_set: false,
  meshy_api_key: '',
  meshy_api_key_set: false,
  hi3d_api_key: '',
  hi3d_api_key_set: false,
  use_director_v2: false,
  nsfw_mode: false,
  nsfw_accepted_at: null,
  director_prompt_polish: 'off',
  workflow_parallelism_enabled: false,
  debug_trace_enabled: false,
  debug_trace_log_path: '',
  civitai_api_key: '',
  civitai_api_key_set: false,
  voice_reference_enabled: false,
  ltx_progressive_pipeline: false,
  show_experimental: false,
}

const SYSTEM_CONFIG = {
  app_version: 'e2e',
  attention_mode: 'sdpa',
  transformer_quantization: 'int8',
  vae_config: 0,
  compile: '',
  video_profile: 4,
  image_profile: 4,
  audio_profile: 4,
  video_output_codec: 'libx264',
  image_output_codec: 'jpeg',
  enhancer_enabled: 0,
  prompt_enhancer_quantization: 'int8',
  attention_modes_available: ['sdpa'],
  vram_safety_coefficient: 0.8,
  model_folders: [],
}

const PRODUCTION_PROFILE = {
  configured: true,
  profile: {
    version: 1,
    text: { provider: 'local', model: '', base_url: '' },
    image: { provider: 'local', model: '' },
    music: { provider: 'local', model: 'ace_step_v1_5_xl_sft_lm_4b' },
    model3d: { provider: 'local', model: 'hunyuan3d-2mini-turbo' },
    video: {
      provider: 'local',
      model: 'minimax_h3_legacy',
      settings: {
        profile: 'quality',
        steps: 20,
        flowShift: 12,
        audioShift: 3,
        turbo: false,
        cache: false,
        loras: [],
        resolution: '540p',
        aspectRatio: '16:9',
      },
    },
  },
}

const EMPTY_STORY_LIBRARY = {
  version: 2,
  revision: 0,
  activeId: '',
  projects: {},
}

const EMPTY_WIZARD_CONVERSATION = {
  version: 1,
  revision: 0,
  messages: [],
  executions: [],
}

const EMPTY_WIZARD_WORKFLOWS = {
  version: 1,
  revision: 0,
  workflows: [],
}

const BACKGROUND_SOURCE_ASSET = {
  id: 'asset-hero',
  kind: 'image',
  filename: 'hero.png',
  size_bytes: 12,
  created_at: 1,
  completed_at: 2,
  metadata_status: 'canonical',
  workspace_ids: ['default'],
  locations: [{
    workspace_id: 'default',
    filename: 'hero.png',
    url: '/api/v1/file/hero.png?workspace=default',
  }],
  url: '/api/v1/file/hero.png?workspace=default',
  origin: { tool: 'studio', actor: 'user', workspace_id: 'default' },
  execution: { status: 'completed' },
  model: { provider: 'local', id: 'flux' },
  prompt_preview: 'A hero image used by the Tools E2E flow',
  manifest: { technical: { width: 1920, height: 1080 } },
}

const BACKGROUND_DERIVED_ASSET = {
  id: 'asset-hero-cutout',
  kind: 'image',
  filename: 'hero-no-background.png',
  size_bytes: 24,
  created_at: 3,
  completed_at: 4,
  metadata_status: 'canonical',
  workspace_ids: ['default'],
  locations: [{
    workspace_id: 'default',
    filename: 'hero-no-background.png',
    url: '/api/v1/file/hero-no-background.png?workspace=default',
  }],
  url: '/api/v1/file/hero-no-background.png?workspace=default',
  origin: {
    tool: 'remove_background',
    capability: 'remove_background',
    actor: 'user',
    workspace_id: 'default',
  },
  execution: {
    status: 'completed',
    job_id: 'tool-bg-e2e',
    task_id: 'task-generation-tool-bg-e2e',
  },
  model: { provider: 'local', id: 'rembg-u2net' },
  prompt_preview: 'Preserve the fine hair and transparent edges',
  manifest: {
    schema_version: 1,
    origin: {
      tool: 'remove_background',
      capability: 'remove_background',
      actor: 'user',
      workspace_id: 'default',
      source_asset_id: 'asset-hero',
    },
    execution: {
      status: 'completed',
      job_id: 'tool-bg-e2e',
      task_id: 'task-generation-tool-bg-e2e',
    },
    generation: {
      model: { provider: 'local', id: 'rembg-u2net' },
      prompts: { instruction: 'Preserve the fine hair and transparent edges' },
    },
    timing: {
      created_at: '2026-09-03T00:00:00Z',
      queued_at: '2026-09-03T00:00:00Z',
      started_at: '2026-09-03T00:00:01Z',
      completed_at: '2026-09-03T00:00:02Z',
      total_ms: 1000,
    },
    provenance: { source_asset_id: 'asset-hero' },
  },
}

const BACKGROUND_DERIVED_OUTPUT = {
  name: 'hero-no-background.png',
  type: 'image',
  mode: 'image',
  favorite: false,
  size: 24,
  created_at: 3,
  completed_at: 4,
  completion_time_source: 'metadata',
  url: '/api/v1/file/hero-no-background.png?workspace=default',
  thumbnail_url: '/api/v1/file/hero-no-background.png?workspace=default',
}

const UPSCALE_DERIVED_ASSET = {
  id: 'asset-hero-upscaled',
  kind: 'image',
  filename: 'hero_upscaled.png',
  size_bytes: 48,
  created_at: 3,
  completed_at: 4,
  metadata_status: 'canonical',
  workspace_ids: ['default'],
  locations: [{
    workspace_id: 'default',
    filename: 'hero_upscaled.png',
    url: '/api/v1/file/hero_upscaled.png?workspace=default',
  }],
  url: '/api/v1/file/hero_upscaled.png?workspace=default',
  origin: {
    tool: 'tools',
    capability: 'upscale',
    actor: 'user',
    workspace_id: 'default',
  },
  execution: {
    status: 'completed',
    job_id: 'tool-upscale-e2e',
    task_id: 'task-generation-tool-upscale-e2e',
  },
  model: { provider: 'local', id: 'post_processing' },
  prompt_preview: '',
  manifest: {
    schema_version: 1,
    origin: {
      tool: 'tools',
      capability: 'upscale',
      actor: 'user',
      workspace_id: 'default',
    },
    execution: {
      status: 'completed',
      job_id: 'tool-upscale-e2e',
      task_id: 'task-generation-tool-upscale-e2e',
    },
    generation: {
      model: { provider: 'local', id: 'post_processing' },
      parameters: { method: 'lanczos2', source_kind: 'image' },
    },
    lineage: {
      parents: [{ id: 'asset-hero', kind: 'image', uri: 'hero.png', role: 'source' }],
      transformations: [{ type: 'upscale', backend: 'lanczos', method: 'lanczos2' }],
    },
  },
}

const UPSCALE_DERIVED_OUTPUT = {
  name: 'hero_upscaled.png',
  type: 'image',
  mode: 'image',
  favorite: false,
  size: 48,
  created_at: 3,
  completed_at: 4,
  completion_time_source: 'metadata',
  url: '/api/v1/file/hero_upscaled.png?workspace=default',
  thumbnail_url: '/api/v1/file/hero_upscaled.png?workspace=default',
}

function json(body: Json, status = 200) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  }
}

function keyFor(method: string, pathname: string): string {
  return `${method.toUpperCase()} ${pathname}`
}

function exactCatalog(): Record<string, ReturnType<typeof json> | { sse: true }> {
  return {
    'GET /api/v1/auth/lan/status': json({
      enabled: false,
      required: false,
      authenticated: true,
    }),
    'GET /api/v1/models': json({
      families: [{ id: 'stub', label: 'Stub', order: 1 }],
      models: [{
        model_type: 'minimax_h3_legacy',
        name: 'H3 Legacy (e2e stub)',
        family: 'stub',
        architecture: 'minimax_h3',
        is_i2v: true,
        is_t2v: true,
        guidance_max_phases: 1,
        fps: 24,
        is_downloaded: false,
      }],
    }),
    'GET /api/v1/model-visibility': json({
      configured: true,
      enabled_models: ['minimax_h3_legacy'],
      initialized_mature_models: [],
      defaults_version: 9,
    }),
    'GET /api/v1/model-selections': json({
      configured: true,
      selected_models: { video: 'minimax_h3_legacy' },
      sources: { video: 'global' },
    }),
    'GET /api/v1/production-profile': json(PRODUCTION_PROFILE),
    'GET /api/v1/workspaces': json({
      workspaces: [{ name: 'default' }],
      active: 'default',
    }),
    'GET /api/v1/outputs': json({ outputs: [], total: 0 }),
    'GET /api/v1/system-config': json(SYSTEM_CONFIG),
    'GET /api/v1/services-config': json(SERVICES_CONFIG),
    'GET /api/v1/llm/status': json({
      loaded: false,
      model_id: null,
      device: null,
      provider: 'local',
    }),
    'GET /api/v1/llm/models': json({ models: [] }),
    'GET /api/v1/jobs': json({ jobs: [] }),
    'GET /api/v1/jobs/recovery': json({ jobs: [] }),
    'GET /api/v1/director/pipelines': json({ pipelines: [], total: 0 }),
    'GET /api/v1/director/pipelines/active': json({ pipelines: [] }),
    'GET /api/v1/system/preflight': json({ ok: true, checks: [] }),
    'GET /api/v1/system-stats': json(SYSTEM_STATS),
    'GET /api/v1/downloads/active': json({ downloads: [] }),
    'GET /api/v1/loras/installed': json({ loras: [], manifest_last_check_at: null }),
    'GET /api/v1/tasks': json({ workspace: 'default', tasks: [], latest_event_id: 0 }),
    'GET /api/v1/tasks/events': { sse: true },
    'GET /api/v1/wizard/conversations': json(EMPTY_WIZARD_CONVERSATION),
    'PUT /api/v1/wizard/conversations': json(EMPTY_WIZARD_CONVERSATION),
    'GET /api/v1/wizard/workflows': json(EMPTY_WIZARD_WORKFLOWS),
    'PUT /api/v1/wizard/workflows': json(EMPTY_WIZARD_WORKFLOWS),
    'GET /api/v1/stories/library': json(EMPTY_STORY_LIBRARY),
    'PUT /api/v1/stories/library': json(EMPTY_STORY_LIBRARY),
    'GET /api/v1/resolutions': json({ resolutions: [] }),
    'GET /api/v1/recipes': json({ recipes: [] }),
    'GET /api/v1/presets': json({ presets: [] }),
    'PUT /api/v1/model-visibility': json({
      configured: true,
      enabled_models: ['minimax_h3_legacy'],
      initialized_mature_models: [],
      defaults_version: 9,
    }),
    'PUT /api/v1/model-selections': json({
      configured: true,
      selected_models: { video: 'minimax_h3_legacy' },
      sources: { video: 'global' },
    }),
    'POST /api/v1/loras/check-updates': json({ updated: 0 }),
    'GET /api/v1/loras/update-manifest': json({ version: 1, entries: [] }),
    'GET /api/v1/models/downloads/status': json({ downloads: {} }),
    'GET /api/v1/system-detect': json({
      auto_enabled: false,
      hardware: {
        cuda_available: false,
        gpu_name: '',
        gpu_vram_gb: 0,
        gpu_capability: '',
        ram_gb: 32,
        cpu_count: 8,
        ram_tier: 'high',
        vram_tier: 'none',
        supports_fp8: false,
        supports_sage: false,
        supports_sage2: false,
        supports_flash: false,
        supports_triton: false,
        supports_nvfp4: false,
      },
      recommended: {
        video_profile: 4,
        image_profile: 4,
        audio_profile: 4,
        transformer_quantization: 'int8',
        vae_config: 0,
        vram_safety_coefficient: 0.8,
        attention_mode: 'sdpa',
        compile: '',
        _recommendation_label: 'CPU stub',
        _recommendation_reason: 'e2e',
      },
    }),
  }
}

function patternedResponse(method: string, pathname: string): ReturnType<typeof json> | null {
  if (method === 'GET' && pathname.startsWith('/api/v1/defaults/')) {
    return json({})
  }
  if (method === 'GET' && pathname.startsWith('/api/v1/model-options/')) {
    return json({})
  }
  if (method === 'GET' && /^\/api\/v1\/loras\/[^/]+\/details$/.test(pathname)) {
    return json({ loras: [], guidance_max_phases: 1, manifest_last_check_at: null })
  }
  if (method === 'GET' && /^\/api\/v1\/loras\/[^/]+$/.test(pathname) && pathname !== '/api/v1/loras/installed') {
    return json({ loras: [], guidance_max_phases: 1 })
  }
  if (method === 'GET' && pathname.startsWith('/api/v1/file/')) {
    return { status: 404, contentType: 'text/plain', body: 'not found' }
  }
  if (method === 'GET' && /^\/api\/v1\/outputs\/[^/]+\/metadata$/.test(pathname)) {
    return json({ source: 'none', params: null })
  }
  return null
}

export async function installApiRoutes(page: Page, options: ApiRouteOptions = {}): Promise<ApiRouteSession> {
  const session: ApiRouteSession = { unhandled: [] }
  const catalog = exactCatalog()
  const discover = process.env.E2E_DISCOVER === '1'
  const backgroundRemovalMode = options.backgroundRemovalMode || 'complete'
  let backgroundRemovalSubmitted = false
  let backgroundRemovalStatusCalls = 0
  let backgroundRemovalCancelRequested = false
  const upscaleMode = options.upscaleMode || 'complete'
  let upscaleSubmitted = false
  let upscaleStatusCalls = 0
  let upscaleCancelRequested = false

  const backgroundAssets = () => [
    BACKGROUND_SOURCE_ASSET,
    ...(backgroundRemovalSubmitted && backgroundRemovalStatusCalls > 1 && !backgroundRemovalCancelRequested && backgroundRemovalMode === 'complete'
      ? [BACKGROUND_DERIVED_ASSET]
      : []),
  ]
  const backgroundStatus = () => {
    if (backgroundRemovalCancelRequested) return {
      status: 'cancelled', progress: 0, step: 0, total_steps: 1,
      phase: 'cancelled', message: 'Background removal cancelled', output_files: [], error: null,
    }
    if (backgroundRemovalMode === 'fail') return {
      status: 'failed', progress: 30, step: 1, total_steps: 3,
      phase: 'removing_background', message: 'Background removal failed', output_files: [], error: 'rembg test failure',
    }
    if (backgroundRemovalStatusCalls < 2) return {
      status: 'running', progress: 45, step: 1, total_steps: 2,
      phase: 'removing_background', message: 'Removing background', output_files: [], error: null,
    }
    return {
      status: 'completed', progress: 100, step: 2, total_steps: 2,
      phase: 'completed', message: 'Background removed', output_files: ['hero-no-background.png'], error: null,
    }
  }
  const toolAssets = () => [
    ...backgroundAssets(),
    ...(upscaleSubmitted && upscaleStatusCalls > 1 && !upscaleCancelRequested && upscaleMode === 'complete'
      ? [UPSCALE_DERIVED_ASSET]
      : []),
  ]
  const upscaleStatus = () => {
    if (upscaleCancelRequested) return {
      status: 'cancelled', progress: 0, step: 0, total_steps: 1,
      phase: 'cancelled', message: 'Upscale cancelled', output_files: [], error: null,
    }
    if (upscaleMode === 'fail') return {
      status: 'failed', progress: 30, step: 1, total_steps: 3,
      phase: 'upscaling', message: 'Upscale failed', output_files: [], error: 'upscale test failure',
    }
    if (upscaleStatusCalls < 2) return {
      status: 'running', progress: 45, step: 1, total_steps: 2,
      phase: 'upscaling', message: 'Upscaling image', output_files: [], error: null,
    }
    return {
      status: 'completed', progress: 100, step: 2, total_steps: 2,
      phase: 'completed', message: 'Image upscaled', output_files: ['hero_upscaled.png'], error: null,
    }
  }

  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method().toUpperCase()
    const pathname = url.pathname

    if (method === 'GET' && pathname === '/api/v1/assets') {
      await route.fulfill(json({ assets: toolAssets(), total: toolAssets().length }))
      return
    }
    if (method === 'GET' && pathname === '/api/v1/assets/asset-hero-cutout') {
      await route.fulfill(json(BACKGROUND_DERIVED_ASSET))
      return
    }
    if (method === 'GET' && pathname === '/api/v1/assets/asset-hero-upscaled') {
      await route.fulfill(json(UPSCALE_DERIVED_ASSET))
      return
    }
    if (method === 'POST' && pathname === '/api/v1/tools/remove-background') {
      backgroundRemovalSubmitted = true
      backgroundRemovalStatusCalls = 0
      backgroundRemovalCancelRequested = false
      await route.fulfill(json({
        job_id: 'tool-bg-e2e',
        task_id: 'task-generation-tool-bg-e2e',
        root_task_id: 'task-generation-tool-bg-e2e',
      }))
      return
    }
    if (method === 'POST' && pathname === '/api/v1/tools/upscale') {
      upscaleSubmitted = true
      upscaleStatusCalls = 0
      upscaleCancelRequested = false
      await route.fulfill(json({
        job_id: 'tool-upscale-e2e',
        task_id: 'task-generation-tool-upscale-e2e',
        root_task_id: 'task-generation-tool-upscale-e2e',
      }))
      return
    }
    if (method === 'GET' && pathname === '/api/v1/status/tool-bg-e2e' && backgroundRemovalSubmitted) {
      backgroundRemovalStatusCalls += 1
      await route.fulfill(json({
        job_id: 'tool-bg-e2e',
        task_id: 'task-generation-tool-bg-e2e',
        root_task_id: 'task-generation-tool-bg-e2e',
        created_at: 1,
        started_at: 2,
        finished_at: backgroundRemovalStatusCalls > 1 ? 3 : null,
        processing_time_sec: backgroundRemovalStatusCalls > 1 ? 1 : null,
        ...backgroundStatus(),
      }))
      return
    }
    if (method === 'GET' && pathname === '/api/v1/status/tool-upscale-e2e' && upscaleSubmitted) {
      upscaleStatusCalls += 1
      await route.fulfill(json({
        job_id: 'tool-upscale-e2e',
        task_id: 'task-generation-tool-upscale-e2e',
        root_task_id: 'task-generation-tool-upscale-e2e',
        created_at: 1,
        started_at: 2,
        finished_at: upscaleStatusCalls > 1 ? 3 : null,
        processing_time_sec: upscaleStatusCalls > 1 ? 1 : null,
        generation_details: {
          generation_mode: 'image', source_kind: 'image', source_asset_id: 'asset-hero',
          capability: 'upscale', method: 'lanczos2',
        },
        ...upscaleStatus(),
      }))
      return
    }
    if (method === 'POST' && pathname === '/api/v1/cancel/tool-bg-e2e') {
      backgroundRemovalCancelRequested = true
      await route.fulfill(json({ status: 'cancelling' }))
      return
    }
    if (method === 'POST' && pathname === '/api/v1/cancel/tool-upscale-e2e') {
      upscaleCancelRequested = true
      await route.fulfill(json({ status: 'cancelling' }))
      return
    }
    if (method === 'GET' && pathname === '/api/v1/outputs' && backgroundRemovalSubmitted && backgroundRemovalStatusCalls > 1 && !backgroundRemovalCancelRequested && backgroundRemovalMode === 'complete') {
      await route.fulfill(json({ outputs: [BACKGROUND_DERIVED_OUTPUT], total: 1 }))
      return
    }
    if (method === 'GET' && pathname === '/api/v1/outputs' && upscaleSubmitted && upscaleStatusCalls > 1 && !upscaleCancelRequested && upscaleMode === 'complete') {
      await route.fulfill(json({ outputs: [UPSCALE_DERIVED_OUTPUT], total: 1 }))
      return
    }
    const exact = catalog[keyFor(method, pathname)]
    if (exact && 'sse' in exact) {
      await route.fulfill({
        status: 200,
        headers: {
          'content-type': 'text/event-stream; charset=utf-8',
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        },
        body: 'retry: 15000\n\n: keepalive\n\n',
      })
      return
    }
    if (exact) {
      await route.fulfill(exact)
      return
    }
    const patterned = patternedResponse(method, pathname)
    if (patterned) {
      await route.fulfill(patterned)
      return
    }
    session.unhandled.push({ method, url: request.url() })
    if (discover) {
      console.log(`E2E_DISCOVER unhandled ${method} ${pathname}`)
      await route.fulfill(json({}))
      return
    }
    await route.fulfill({
      status: 501,
      contentType: 'application/json',
      body: JSON.stringify({ detail: `Unhandled E2E route ${method} ${pathname}` }),
    })
  })

  return session
}

export function formatUnhandled(session: ApiRouteSession): string {
  if (!session.unhandled.length) return ''
  const unique = [...new Set(session.unhandled.map(item => `${item.method} ${item.url}`))]
  return unique.join('\n')
}
