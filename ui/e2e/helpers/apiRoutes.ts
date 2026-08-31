import type { Page } from '@playwright/test'

export const RUNTIME_IDENTITY = {
  instance_id: 'e2e-instance',
  ui_build_id: 'e2e-ui-build',
} as const

type Json = Record<string, unknown> | unknown[]

export interface ApiRouteSession {
  unhandled: Array<{ method: string; url: string }>
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
  return null
}

export async function installApiRoutes(page: Page): Promise<ApiRouteSession> {
  const session: ApiRouteSession = { unhandled: [] }
  const catalog = exactCatalog()
  const discover = process.env.E2E_DISCOVER === '1'

  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method().toUpperCase()
    const pathname = url.pathname
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
