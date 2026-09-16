import type { ModelResourceRequirements } from '../types'
import { h3CatalogEntry } from './h3Catalog'

/** Variant labels shown like MiniMax H3's Pruned / Full / Fused / Legacy lines. */
export type ModelVariant =
  | 'pruned'
  | 'full'
  | 'fast'
  | 'legacy'
  | 'distilled'
  | 'quantized'
  | 'gguf'
  | 'nvfp4'
  | 'small'
  | 'edit'
  | 'standard'
  | 'tool'

export type ModelCapability =
  | 'videoT2v'
  | 'videoI2v'
  | 'videoBoth'
  | 'videoFirstLast'
  | 'videoAudio'
  | 'videoAudioI2v'
  | 'videoAudioFirstLast'
  | 'videoTalking'
  | 'videoEdit'
  | 'videoControl'
  | 'image'
  | 'imageEdit'
  | 'imageRefs'
  | 'music'
  | 'speech'
  | 'sfx'
  | 'model3d'
  | 'model3dImage'
  | 'model3dMultiview'
  | 'tool'

export interface ModelCatalogInput {
  model_type: string
  name?: string
  architecture?: string
  family?: string
  description?: string
  selector_help?: string
  resource_requirements?: ModelResourceRequirements
  is_i2v?: boolean
  is_t2v?: boolean
  generates_audio?: boolean
  supports_end_frame?: boolean
  supports_ref_images?: boolean
  tool_only?: boolean
}

export interface CatalogRequirements {
  vram_gb?: number
  ram_gb?: number
  storage_gb?: number
  comfortable_vram_gb?: number
}

export interface ResolvedModelCatalog {
  variant: ModelVariant
  capability: ModelCapability
  requirements: CatalogRequirements
  fromApi: boolean
}

const IMAGE_FAMILIES = new Set(['flux', 'flux2', 'qwen', 'z_image', 'krea2', 'hidream', 'minimax'])
const IMAGE_ARCH = /^(flux|pi_flux2|qwen_image|z_image|krea2|hidream|minimax_image)/
const MUSIC_ARCH = /^(ace_step|minimax_music|heartmula|yue2)/
const SPEECH_ARCH = /^(chatterbox|qwen3_tts|kugelaudio|index_tts2|auk)/
const TALKING = /multitalk|infinitetalk|fantasy|avatar|steadydancer|longcat_avatar|animate/
const VIDEO_EDIT = /lucy_edit|kiwi_edit|chrono_edit|viggle|scail|recast|wanmove/
const VIDEO_CONTROL = /vace|standin|mocha|phantom|sky_df|recam|fun_inp|lynx/

const VARIANT_TOKENS: Array<[ModelVariant, string[]]> = [
  ['legacy', ['legacy']],
  ['pruned', ['pruned']],
  ['gguf', ['gguf']],
  ['nvfp4', ['nvfp4']],
  ['quantized', ['nunchaku', 'int4']],
  ['fast', ['fused', 'fastwan', 'lightning', 'schnell', 'twinflow', 'turbo']],
  ['distilled', ['fusionix', 'klein']],
  ['edit', ['edit', 'inpaint', 'outpaint', 'control', 'kontext', 'uso', 'umo', 'dreamomni', 'dreamomni2']],
  ['small', ['4b', 'lite']],
  ['full', ['full']],
]

const EXACT_REQUIREMENTS: Record<string, CatalogRequirements> = {
  trellis2: { vram_gb: 24, ram_gb: 32 },
  pixal3d: { vram_gb: 12, ram_gb: 16 },
  unirig: { vram_gb: 8, ram_gb: 16 },
  'hunyuan3d-2.1': { vram_gb: 10, ram_gb: 16 },
}

const ARCH_REQUIREMENTS: Array<[string, CatalogRequirements]> = [
  // No measured memory minima yet. Avoid inventing the generic model estimate.
  ['yue2', {}],
  ['auk', {}],
  ['minimax_music3', { vram_gb: 24, ram_gb: 32, storage_gb: 28, comfortable_vram_gb: 24 }],
  ['h3_advanced', { vram_gb: 24, ram_gb: 32, comfortable_vram_gb: 24 }],
  ['minimax_h3', { vram_gb: 24, ram_gb: 32, comfortable_vram_gb: 24 }],
  ['flux2_klein_4b', { vram_gb: 6, ram_gb: 16 }],
  ['flux2_klein_9b', { vram_gb: 8, ram_gb: 16 }],
  ['pi_flux2', { vram_gb: 8, ram_gb: 32, comfortable_vram_gb: 16 }],
  ['flux2', { vram_gb: 8, ram_gb: 32, comfortable_vram_gb: 16 }],
  ['flux', { vram_gb: 8, ram_gb: 16 }],
  ['qwen_image', { vram_gb: 12, ram_gb: 24, storage_gb: 20 }],
  ['z_image', { vram_gb: 6, ram_gb: 16 }],
  ['krea2', { vram_gb: 8, ram_gb: 16 }],
  ['hidream', { vram_gb: 12, ram_gb: 24 }],
  ['ltx2_19B', { vram_gb: 12, ram_gb: 32, storage_gb: 20, comfortable_vram_gb: 24 }],
  ['ltx2', { vram_gb: 16, ram_gb: 32, storage_gb: 24, comfortable_vram_gb: 24 }],
  ['ltxv', { vram_gb: 10, ram_gb: 16 }],
  ['hunyuan_1_5', { vram_gb: 12, ram_gb: 32, comfortable_vram_gb: 20 }],
  ['hunyuan', { vram_gb: 12, ram_gb: 32 }],
  ['ovi', { vram_gb: 8, ram_gb: 16 }],
  ['scail2', { vram_gb: 12, ram_gb: 24 }],
  ['scail', { vram_gb: 10, ram_gb: 16 }],
  ['lucy', { vram_gb: 10, ram_gb: 16 }],
  ['viggle', { vram_gb: 8, ram_gb: 16 }],
  ['longcat', { vram_gb: 12, ram_gb: 24 }],
  ['k5_lite', { vram_gb: 8, ram_gb: 16 }],
  ['k5_pro', { vram_gb: 12, ram_gb: 24 }],
  ['sensenova', { vram_gb: 10, ram_gb: 16 }],
  ['chrono_edit', { vram_gb: 8, ram_gb: 16 }],
  ['kiwi_edit', { vram_gb: 8, ram_gb: 16 }],
  ['infinitetalk', { vram_gb: 8, ram_gb: 16 }],
  ['multitalk', { vram_gb: 8, ram_gb: 16 }],
  ['steadydancer', { vram_gb: 8, ram_gb: 16 }],
  ['fun_inp', { vram_gb: 10, ram_gb: 24 }],
  ['phantom', { vram_gb: 10, ram_gb: 24 }],
  ['sky_df', { vram_gb: 10, ram_gb: 24 }],
  ['flf2v', { vram_gb: 8, ram_gb: 16 }],
  ['alpha2', { vram_gb: 8, ram_gb: 16 }],
  ['alpha', { vram_gb: 8, ram_gb: 16 }],
  ['animate', { vram_gb: 8, ram_gb: 16 }],
  ['fantasy', { vram_gb: 8, ram_gb: 16 }],
  ['lynx', { vram_gb: 10, ram_gb: 24 }],
  ['mocha', { vram_gb: 10, ram_gb: 24 }],
  ['standin', { vram_gb: 10, ram_gb: 24 }],
  ['i2v_2_2', { vram_gb: 10, ram_gb: 24 }],
  ['t2v_2_2', { vram_gb: 10, ram_gb: 24 }],
  ['ti2v', { vram_gb: 10, ram_gb: 24 }],
  ['vace', { vram_gb: 10, ram_gb: 24 }],
  ['i2v', { vram_gb: 8, ram_gb: 16 }],
  ['t2v', { vram_gb: 8, ram_gb: 16 }],
  ['wan', { vram_gb: 8, ram_gb: 16 }],
  ['ace_step', { vram_gb: 6, ram_gb: 16 }],
  ['heartmula', { vram_gb: 6, ram_gb: 16 }],
  ['chatterbox', { vram_gb: 4, ram_gb: 16 }],
  ['qwen3_tts', { vram_gb: 6, ram_gb: 16 }],
  ['kugelaudio', { vram_gb: 6, ram_gb: 16 }],
  ['index_tts2', { vram_gb: 8, ram_gb: 16 }],
  ['mmaudio', { vram_gb: 6, ram_gb: 16 }],
  ['scenema', { vram_gb: 8, ram_gb: 16 }],
  ['dramabox', { vram_gb: 8, ram_gb: 16 }],
]

const DEFAULT_REQUIREMENTS: CatalogRequirements = { vram_gb: 8, ram_gb: 16 }
const COMPACT_1_3B: CatalogRequirements = { vram_gb: 6, ram_gb: 16, storage_gb: 4 }
const HUNYUAN3D_MINI: CatalogRequirements = { vram_gb: 6, ram_gb: 16 }
const HUNYUAN3D_DEFAULT: CatalogRequirements = { vram_gb: 8, ram_gb: 16 }

function catalogTokens(model: ModelCatalogInput): string[] {
  return `${model.model_type} ${model.architecture || ''} ${model.name || ''}`
    .toLowerCase()
    .split(/[^a-z0-9.]+/)
    .filter(Boolean)
}

function tokenLooksQuantized(part: string): boolean {
  return part.includes('fp8')
}

function tokenLooksDistilled(part: string): boolean {
  return part.includes('distill') || part === 'sf' || part.endsWith('.sf')
}

function tokenLooksCompact(part: string): boolean {
  return part.includes('1.3b') || (part.endsWith('mini') && part !== 'minimax')
}

export function detectVariant(model: ModelCatalogInput): ModelVariant {
  if (model.tool_only) return 'tool'
  const h3 = h3CatalogEntry(model.model_type)
  if (h3) return h3.variant
  const parts = catalogTokens(model)
  const matched = VARIANT_TOKENS.find(([, tokens]) => tokens.some(token => parts.includes(token)))
  if (matched) return matched[0]
  if (parts.some(tokenLooksQuantized)) return 'quantized'
  if (parts.some(tokenLooksDistilled)) return 'distilled'
  if (parts.some(tokenLooksCompact)) return 'small'
  return 'standard'
}

function isMeshModel(model: ModelCatalogInput): boolean {
  const type = model.model_type
  return model.family === 'hunyuan3d'
    || model.architecture === 'hunyuan3d'
    || type.startsWith('hunyuan3d')
    || type === 'trellis2'
    || type === 'pixal3d'
}

function meshCapability(model: ModelCatalogInput): ModelCapability {
  if (model.model_type.includes('2mv')) return 'model3dMultiview'
  if (model.is_i2v && !model.is_t2v) return 'model3dImage'
  return 'model3d'
}

function imageCapability(model: ModelCatalogInput): ModelCapability {
  if (detectVariant(model) === 'edit') return 'imageEdit'
  if (model.supports_ref_images) return 'imageRefs'
  return 'image'
}

function videoCapability(model: ModelCatalogInput): ModelCapability {
  if (model.generates_audio && model.supports_end_frame) return 'videoAudioFirstLast'
  if (model.generates_audio && model.is_i2v) return 'videoAudioI2v'
  if (model.generates_audio) return 'videoAudio'
  if (model.supports_end_frame) return 'videoFirstLast'
  if (model.is_i2v && model.is_t2v) return 'videoBoth'
  if (model.is_i2v) return 'videoI2v'
  return 'videoT2v'
}

export function detectCapability(model: ModelCatalogInput): ModelCapability {
  const type = model.model_type
  const arch = model.architecture || ''
  if (model.tool_only || type === 'unirig' || arch === 'unirig') return 'tool'
  if (isMeshModel(model)) return meshCapability(model)
  if (type.startsWith('mmaudio') || arch === 'mmaudio') return 'sfx'
  if (MUSIC_ARCH.test(arch) || type.startsWith('ace_step') || type.startsWith('minimax_music') || type.startsWith('heartmula')) {
    return 'music'
  }
  if (SPEECH_ARCH.test(arch) || model.family === 'tts') return 'speech'
  if (IMAGE_FAMILIES.has(model.family || '') || IMAGE_ARCH.test(arch)) return imageCapability(model)
  if (TALKING.test(type) || model.family === 'longcat') return 'videoTalking'
  if (VIDEO_EDIT.test(type)) return 'videoEdit'
  if (VIDEO_CONTROL.test(type) || VIDEO_CONTROL.test(arch)) return 'videoControl'
  return videoCapability(model)
}

function prefixRequirements(modelType: string, architecture: string): CatalogRequirements | undefined {
  return ARCH_REQUIREMENTS.find(([prefix]) => architecture.startsWith(prefix) || modelType.startsWith(prefix))?.[1]
}

export function catalogRequirementKey(modelType: string, architecture: string): string {
  if (EXACT_REQUIREMENTS[modelType]) return `exact:${modelType}`
  if (modelType.startsWith('hunyuan3d-2mini')) return 'hunyuan3d-mini'
  if (modelType.startsWith('hunyuan3d')) return 'hunyuan3d'
  if (/1\.3b/i.test(`${modelType} ${architecture}`)) return '1.3b'
  const prefix = ARCH_REQUIREMENTS.find(([key]) => architecture.startsWith(key) || modelType.startsWith(key))?.[0]
  return prefix ? `prefix:${prefix}` : 'fallback'
}

function typicalRequirements(modelType: string, architecture: string): CatalogRequirements {
  const exact = EXACT_REQUIREMENTS[modelType]
  if (exact) return exact
  if (modelType.startsWith('hunyuan3d-2mini')) return HUNYUAN3D_MINI
  if (modelType.startsWith('hunyuan3d')) return HUNYUAN3D_DEFAULT
  if (/1\.3b/i.test(`${modelType} ${architecture}`)) return COMPACT_1_3B
  return prefixRequirements(modelType, architecture) || DEFAULT_REQUIREMENTS
}

function applyVariantModifiers(
  variant: ModelVariant,
  requirements: CatalogRequirements,
): CatalogRequirements {
  if (requirements.vram_gb == null) return requirements
  if (variant === 'gguf') return { ...requirements, vram_gb: Math.max(6, requirements.vram_gb - 4) }
  if (variant === 'nvfp4' || variant === 'quantized') {
    return { ...requirements, vram_gb: Math.max(6, requirements.vram_gb - 2) }
  }
  return requirements
}

function mergeApiRequirements(
  catalog: CatalogRequirements,
  api?: ModelResourceRequirements,
): { requirements: CatalogRequirements; fromApi: boolean } {
  if (!api) return { requirements: catalog, fromApi: false }
  const hasAny = api.vram_gb != null || api.ram_gb != null || api.storage_gb != null
  if (!hasAny) return { requirements: catalog, fromApi: false }
  return {
    fromApi: true,
    requirements: {
      vram_gb: api.vram_gb ?? catalog.vram_gb,
      ram_gb: api.ram_gb ?? catalog.ram_gb,
      storage_gb: api.storage_gb ?? catalog.storage_gb,
      comfortable_vram_gb: catalog.comfortable_vram_gb,
    },
  }
}

export function resolveModelCatalog(model: ModelCatalogInput): ResolvedModelCatalog {
  const variant = detectVariant(model)
  const capability = detectCapability(model)
  const typical = applyVariantModifiers(
    variant,
    typicalRequirements(model.model_type, model.architecture || ''),
  )
  const merged = mergeApiRequirements(typical, model.resource_requirements)
  return { variant, capability, ...merged }
}

/** Badge VRAM. H3 keeps its measured-memory block instead of a typical minimum. */
export function catalogVramGb(model: ModelCatalogInput): number | undefined {
  if (h3CatalogEntry(model.model_type)) return model.resource_requirements?.vram_gb
  return resolveModelCatalog(model).requirements.vram_gb
}
