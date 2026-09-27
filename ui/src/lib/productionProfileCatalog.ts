import type { LlmModelOption, ModelDef } from '../types'

export type CatalogOption = { id: string; label: string }

export function keepCurrentOption(options: CatalogOption[], current: string): CatalogOption[] {
  if (current && !options.some(option => option.id === current)) {
    return [{ id: current, label: current }, ...options]
  }
  return options
}

export const MINIMAX_TEXT_MODELS: CatalogOption[] = [
  { id: 'MiniMax-M3', label: 'MiniMax M3' },
  { id: 'MiniMax-M2.7', label: 'MiniMax M2.7' },
  { id: 'MiniMax-M2.7-highspeed', label: 'MiniMax M2.7 Highspeed' },
]

export const DEEPSEEK_TEXT_MODELS: CatalogOption[] = [
  { id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro' },
  { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash' },
]

export const ANTHROPIC_TEXT_MODELS: CatalogOption[] = [
  { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
]

export const GROK_TEXT_MODELS: CatalogOption[] = [
  { id: 'grok-4', label: 'grok-4' },
  { id: 'grok-4-fast', label: 'grok-4-fast' },
  { id: 'grok-3', label: 'grok-3' },
  { id: 'grok-3-mini', label: 'grok-3-mini' },
]

export const OPENAI_TEXT_MODELS: CatalogOption[] = [
  { id: 'gpt-4.1', label: 'gpt-4.1' },
]

const STATIC_TEXT_MODELS: Record<string, CatalogOption[]> = {
  minimax: MINIMAX_TEXT_MODELS,
  deepseek: DEEPSEEK_TEXT_MODELS,
  anthropic: ANTHROPIC_TEXT_MODELS,
  grok: GROK_TEXT_MODELS,
  openai: OPENAI_TEXT_MODELS,
}

function mergeCatalog(primary: CatalogOption[], extra: CatalogOption[]): CatalogOption[] {
  const seen = new Set<string>()
  const merged: CatalogOption[] = []
  for (const option of [...primary, ...extra]) {
    if (seen.has(option.id)) continue
    seen.add(option.id)
    merged.push(option)
  }
  return merged
}

export function listedTextModels(llmModels: LlmModelOption[], provider: string): CatalogOption[] {
  const filtered = llmModels
    .filter(model => {
      const modelProvider = model.provider || 'local'
      if (provider === 'local') return modelProvider === 'local'
      return modelProvider === provider
    })
    .map(model => ({ id: model.id, label: model.label }))
  return mergeCatalog(filtered, STATIC_TEXT_MODELS[provider] || [])
}

export function textModelOptions(
  llmModels: LlmModelOption[],
  provider: string,
  current: string,
): CatalogOption[] {
  return keepCurrentOption(listedTextModels(llmModels, provider), current)
}

export function defaultTextModel(
  provider: string,
  current: string,
  llmModels: LlmModelOption[],
): string {
  const listed = listedTextModels(llmModels, provider)
  if (listed.some(option => option.id === current)) return current
  return listed[0]?.id || ''
}

export function defaultTextBaseUrl(provider: string, current: string): string {
  if (provider === 'ollama') return current || 'http://127.0.0.1:11434'
  if (provider === 'grok') return 'https://api.x.ai'
  if (provider === 'minimax') return 'https://api.minimax.io'
  if (provider === 'openai') return current || 'https://api.openai.com'
  if (provider === 'deepseek') return 'https://api.deepseek.com'
  return current
}

export const MINIMAX_IMAGE_MODELS: CatalogOption[] = [
  { id: 'image-01', label: 'image-01' },
]

export const MINIMAX_MUSIC_MODELS: CatalogOption[] = [
  { id: 'music-3.0', label: 'Music 3.0' },
  { id: 'music-2.6', label: 'Music 2.6' },
]

export const HUNYUAN3D_PROFILE_MODELS: CatalogOption[] = [
  'hunyuan3d-2mini-turbo',
  'hunyuan3d-2mini-fast',
  'hunyuan3d-2mini',
  'hunyuan3d-2-turbo',
  'hunyuan3d-2-fast',
  'hunyuan3d-2',
  'hunyuan3d-2mv-turbo',
  'hunyuan3d-2mv-fast',
  'hunyuan3d-2mv',
  'hunyuan3d-2.1',
].map(id => ({ id, label: id }))

export const MESHY_PROFILE_MODELS: CatalogOption[] = [
  { id: 'latest', label: 'latest' },
]

export const HI3D_PROFILE_MODELS: CatalogOption[] = [
  { id: 'hitem3dv2.1', label: 'hitem3dv2.1' },
]

export function downloadedModelOptions(models: ModelDef[], familyIds: string[]): CatalogOption[] {
  return models
    .filter(model => familyIds.includes(model.family) && !model.tool_only && model.is_downloaded !== false)
    .map(model => ({ id: model.model_type, label: model.name || model.model_type }))
}

export function defaultImageModel(
  provider: string,
  localOptions: CatalogOption[],
  current: string,
): string {
  if (provider === 'minimax') return 'image-01'
  if (localOptions.some(option => option.id === current)) return current
  return localOptions[0]?.id || current
}

export function model3dProfileOptions(provider: string, hunyuanOptions: CatalogOption[]): CatalogOption[] {
  if (provider === 'meshy') return MESHY_PROFILE_MODELS
  if (provider === 'hi3d') return HI3D_PROFILE_MODELS
  return hunyuanOptions.length ? hunyuanOptions : HUNYUAN3D_PROFILE_MODELS
}

export function defaultModel3dModel(provider: string): string {
  if (provider === 'meshy') return 'latest'
  if (provider === 'hi3d') return 'hitem3dv2.1'
  return 'hunyuan3d-2mini-turbo'
}
