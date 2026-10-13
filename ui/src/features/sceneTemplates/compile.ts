import { finishTemplateLayers, TEMPLATE_FINISH_VERSION } from './templateFinish'
import type { Scene, SceneLayer } from '../../types'
// The i18next instance src/i18n initializes at app start. E2E specs load this module in Node,
// where src/i18n's locale JSON cannot load, so it is not imported here.
import i18n from 'i18next'
import { canonicalBindings, requiredSlots, resolveSceneTemplate, templateCatalogVersion, type SceneTemplateDefinition, type TemplateSlotName } from './catalog'
import { backdrop, foreground, type BuildContext, type TemplateAsset, type TemplateBindings } from './sceneBuilders'
import { resolveControls, type TemplateControlInput, type TemplateControlValues } from './templateControls'
import { TemplateError } from './templateErrors'
import { withCameraDrift } from './cameraDrift'
import { cinemaScenes } from './cinemaScenes'
import { walkPlates, walkScenes } from './walkScenes'
import { musicScenes } from './musicScenes'
import { spaceScenes } from './spaceScenes'
import { musicMotionSolo } from './musicMotionSolo'
import { musicMotionEnsemble } from './musicMotionEnsemble'
import { musicMotionBackground } from './musicMotionBuilders'
import { video2dScenes, type Video2dFrame } from './video2dCandidates'
export type { TemplateBindings, TemplateControls, TemplateAsset } from './sceneBuilders'
export type { TemplateControlInput } from './templateControls'

/** Bindings as callers send them: the slot names of the card, or the old names (hero, plate, prop). */
export type TemplateBindingsInput = Readonly<Record<string, TemplateAsset | undefined>>

const builders = { ...cinemaScenes, ...walkScenes, ...musicScenes, ...spaceScenes, ...musicMotionSolo, ...musicMotionEnsemble }
const DISTINCT_MUSIC_SLOTS = ['subject_1', 'subject_2', 'prop_1'] as const

function validateAsset(value: TemplateAsset) {
  if (typeof value.source !== 'string' || !value.source.trim() || value.source.length > 2_000_000) throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.durableResource'))
  if (!/^(?:data:(?:image\/|model\/gltf-binary;)|\/api\/v1\/|\/examples\/|https?:\/\/)/i.test(value.source)) throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.libraryOrDurable'))
  // HTTP/API references are checked by the media loader; only inline MIME is known here.
  if (/^data:/i.test(value.source)) {
    const matchesKind = value.type === 'image' ? /^data:image\//i : /^data:model\/gltf-binary;/i
    if (!matchesKind.test(value.source)) throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.mimeMismatch'))
  }
}
function validateBindings(template: SceneTemplateDefinition, bindings: TemplateBindings, controls: TemplateControlValues) {
  const needed = new Set(requiredSlots(template, controls).map(slot => slot.id))
  for (const slot of template.slots) {
    const value = bindings[slot.id]
    if (!value && needed.has(slot.id)) throw new TemplateError('template_missing_slot', i18n.t('scene3d:templateCompile.missingSlot', { slot: slot.id }))
    if (!value) continue
    if (!slot.kinds.includes(value.type)) throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.slotRejects', { slot: slot.id, type: value.type }))
    validateAsset(value)
  }
  // The choreographies repeat and swap figures, so their identity slots must be distinct assets; the original
  // grammars keep allowing the same picture twice.
  if (template.group === 'music-motion') validateDistinctMusicSlots(bindings)
  const models = Object.values(bindings).filter(value => value?.type === 'model3d').map(value => value!.source)
  if (new Set(models).size !== models.length) throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.repeatedGlb'))
}

function validateDistinctMusicSlots(bindings: TemplateBindings) {
  const sources = new Map<string, string>()
  const assetIds = new Map<string, string>()
  for (const slot of DISTINCT_MUSIC_SLOTS) {
    const binding = bindings[slot]
    if (!binding) continue

    const previousSourceSlot = sources.get(binding.source)
    if (previousSourceSlot) {
      throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.musicSourceReuse', { left: previousSourceSlot, right: slot }))
    }
    sources.set(binding.source, slot)

    const assetId = binding.catalogAtAssignment?.assetId
    if (typeof assetId !== 'string' || !assetId.trim()) continue
    const previousAssetSlot = assetIds.get(assetId)
    if (previousAssetSlot) {
      throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.musicAssetReuse', { left: previousAssetSlot, right: slot, assetId }))
    }
    assetIds.set(assetId, slot)
  }
}

type SceneBody = Pick<Scene, 'width' | 'height' | 'fps' | 'layers'> & Partial<Pick<Scene, 'texts' | 'finish'>>

function layerScene(template: SceneTemplateDefinition, ctx: BuildContext): SceneBody {
  const build = builders[template.id]
  if (!build) throw new TemplateError('template_unknown', i18n.t('scene3d:templateCompile.noCompiler', { id: template.id }))
  const walk = walkPlates[template.id]?.(ctx)
  const background = template.group === 'music-motion' ? musicMotionBackground(template.id, ctx) : [{ ...backdrop(ctx), ...walk?.plate }]
  const front = foreground(ctx).map(item => ({ ...item, ...walk?.foreground }))
  const built = withCameraDrift([...background, ...build(ctx), ...front], ctx)
  return { width: 1280, height: 720, fps: 30, layers: finishTemplateLayers(built, template.family, ctx.intensity) }
}

function sceneBody(template: SceneTemplateDefinition, ctx: BuildContext, frame: Video2dFrame): SceneBody {
  const video2d = video2dScenes[template.id]
  return template.group === 'video2d' && video2d ? video2d(ctx, frame) : layerScene(template, ctx)
}

function checkBudget(layers: SceneLayer[]) {
  if (layers.length > 24 || layers.filter(item => item.type === 'model3d').length > 2) throw new TemplateError('template_compile_failed', i18n.t('scene3d:templateCompile.overBudget'))
}

/**
 * Compile one card (or an alias of one) with provided assets. Old slot names and alias ids are translated here, so
 * the composer, the MCP bridge and saved recipes share one entry; errors carry the codes the Python compile uses.
 */
export function compileCandidateScene(id: string, input: TemplateBindingsInput, options: TemplateControlInput = {}, frame: Video2dFrame = {}): Scene {
  const { template, alias, preset } = resolveSceneTemplate(id)
  const controls = resolveControls(template, preset, options)
  const bindings = canonicalBindings<TemplateAsset>(template, input) as TemplateBindings
  validateBindings(template, bindings, controls)
  const ctx: BuildContext = {
    duration: Number(controls.duration), bpm: Number(controls.bpm), intensity: Number(controls.intensity),
    bindings, options: controls, base: template.defaultDuration,
  }
  const body = sceneBody(template, ctx, frame)
  checkBudget(body.layers)
  return {
    version: 1, name: `${template.title}${template.status === 'candidate' ? ` · ${i18n.t('scene3d:templateCompile.candidateSuffix')}` : ''}`, generationPolicy: 'provided_only',
    ...body, duration: ctx.duration,
    narrative: { templateId: template.id, category: template.family, visualIntent: template.description,
      controls: { ...controls, ...(alias ? { alias } : {}), finishVersion: TEMPLATE_FINISH_VERSION, catalogVersion: templateCatalogVersion(template), templateVersion: template.version, reviewStatus: template.status, renderer: 'layer-compositor-v1' },
      assets: (Object.entries(bindings) as Array<[TemplateSlotName, TemplateAsset | undefined]>).filter(([, value]) => value).map(([slot, value]) => ({ slot, source: value!.source, name: value!.name, type: value!.type,
        ...(value!.catalogAtAssignment ? { catalogAtAssignment: { ...value!.catalogAtAssignment } } : {}),
      })),
      prompt: template.promptExample, evaluationCues: [...template.limits],
    },
  }
}
