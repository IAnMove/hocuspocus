import { campaignCard } from './campaignTemplates'
import { actionCard } from './actionTemplates'
import { animeCard } from './animeTemplates'
import { transitionCard } from './transitionTemplates'
import { speedCard } from './speedTemplates'
import { titleCard } from './titleTemplates'
import { atmosSet, isAtmosDressing } from './atmos/registry.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES, type Scene3DTemplate, type Scene3DTemplateFilter, type Scene3DTemplateId } from './templates'
import { templateTraits, templateTraitWords, type TemplateTraits } from './templateTraits.ts'
import type { Scene3DDressing } from './types.ts'

export const TEMPLATE_SETTINGS = [
  'sea', 'city', 'rooftop', 'hangar', 'desert', 'train', 'moon', 'space',
  'jungle', 'forest', 'snow', 'casino', 'studio', 'street', 'stage', 'canyon', 'cave', 'volcano', 'islands', 'room', 'grid', 'circuit', 'mainframe',
] as const
export type TemplateSetting = typeof TEMPLATE_SETTINGS[number]
const MOTION_SETTINGS: Partial<Record<Scene3DDressing, TemplateSetting>> = {
  'motion-seasonal-carriage': 'train', 'motion-data-assembly': 'mainframe',
  'motion-sunset-flight': 'sea', 'motion-lighthouse-story': 'sea',
  'motion-bouncing-ball': 'stage', 'motion-music-machine': 'stage',
}

export function settingFromDressing(dressing: Scene3DDressing | undefined): TemplateSetting {
  const motion = MOTION_SETTINGS[dressing ?? 'none']
  if (motion) return motion
  if (dressing === 'open-sea') return 'sea'
  if (dressing === 'lunar') return 'moon'
  if (dressing === 'rooftop') return 'rooftop'
  if (dressing === 'hangar') return 'hangar'
  if (dressing === 'desert') return 'desert'
  if (dressing === 'train') return 'train'
  if (dressing === 'space-lane' || dressing === 'space') return 'space'
  if (dressing === 'jungle') return 'jungle'
  if (isAtmosDressing(dressing)) return atmosTemplateSetting(dressing)
  if (dressing === 'snow') return 'snow'
  if (dressing === 'casino') return 'casino'
  if (dressing === 'chase-street' || dressing === 'street' || dressing === 'drive-city' || dressing === 'drive-coast' || dressing === 'drive-tunnel') return 'city'
  if (dressing === 'cafe') return 'street'
  if (dressing === 'treadmill') return 'stage'
  return 'studio'
}

function atmosTemplateSetting(dressing: string | undefined): TemplateSetting {
  const setting = atmosSet(dressing)?.setting
  if (setting && (TEMPLATE_SETTINGS as readonly string[]).includes(setting)) return setting as TemplateSetting
  return 'studio'
}

export function templateSetting(id: Scene3DTemplateId): TemplateSetting {
  return settingFromDressing(applyScene3DTemplate(id).dressing)
}

const traits = new Map<Scene3DTemplateId, TemplateTraits>()
/** The shot's derived traits (shot size, camera moves, what moves, uses), read once from the built document. */
export function templateTraitsOf(id: Scene3DTemplateId): TemplateTraits {
  if (!traits.has(id)) traits.set(id, templateTraits(applyScene3DTemplate(id), { category: TEMPLATE_CATEGORIES[id] }))
  return traits.get(id)!
}

function templateSearchText(item: Scene3DTemplate, input: {
  locale: 'en' | 'es'
  titleOf: (id: Scene3DTemplateId) => string
}) {
  const card = campaignCard(item.id, input.locale) ?? actionCard(item.id, input.locale) ?? animeCard(item.id, input.locale)
    ?? transitionCard(item.id, input.locale) ?? speedCard(item.id, input.locale) ?? titleCard(item.id, input.locale)
  return `${input.titleOf(item.id)} ${card?.description ?? ''} ${card?.requirements.join(' ') ?? ''} ${item.id} ${item.tags?.join(' ').replaceAll('-', ' ') ?? ''} ${templateSetting(item.id)} ${templateTraitWords(templateTraitsOf(item.id)).join(' ')}`
}

function templateMatchesFilter(item: Scene3DTemplate, input: {
  category: 'all' | Scene3DTemplateFilter
  setting: 'all' | TemplateSetting
  locale: 'en' | 'es'
  titleOf: (id: Scene3DTemplateId) => string
}, needle: string) {
  if (input.category !== 'all' && TEMPLATE_CATEGORIES[item.id] !== input.category && !item.tags?.some(tag => tag === input.category)) return false
  if (input.setting !== 'all' && templateSetting(item.id) !== input.setting) return false
  return !needle || templateSearchText(item, input).toLocaleLowerCase().includes(needle)
}

export function filterScene3DTemplates(input: {
  category: 'all' | Scene3DTemplateFilter
  setting: 'all' | TemplateSetting
  query: string
  locale: 'en' | 'es'
  titleOf: (id: Scene3DTemplateId) => string
}): Scene3DTemplate[] {
  const needle = input.query.trim().toLocaleLowerCase()
  return SCENE3D_TEMPLATES.filter(item => templateMatchesFilter(item, input, needle))
}

export function settingsIn(templates: readonly Scene3DTemplate[]): TemplateSetting[] {
  const seen = new Set<TemplateSetting>()
  for (const item of templates) seen.add(templateSetting(item.id))
  return TEMPLATE_SETTINGS.filter(setting => seen.has(setting))
}
