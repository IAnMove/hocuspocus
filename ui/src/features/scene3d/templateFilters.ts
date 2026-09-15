import { campaignCard } from './campaignTemplates'
import { actionCard } from './actionTemplates'
import { applyScene3DTemplate, SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES, type Scene3DTemplate, type Scene3DTemplateCategory, type Scene3DTemplateId } from './templates'
import type { Scene3DDressing } from './types.ts'

export const TEMPLATE_SETTINGS = [
  'sea', 'city', 'rooftop', 'hangar', 'desert', 'train', 'moon', 'space',
  'jungle', 'snow', 'casino', 'studio', 'street', 'stage',
] as const
export type TemplateSetting = typeof TEMPLATE_SETTINGS[number]

export function settingFromDressing(dressing: Scene3DDressing | undefined): TemplateSetting {
  if (dressing === 'open-sea') return 'sea'
  if (dressing === 'lunar') return 'moon'
  if (dressing === 'rooftop') return 'rooftop'
  if (dressing === 'hangar') return 'hangar'
  if (dressing === 'desert') return 'desert'
  if (dressing === 'train') return 'train'
  if (dressing === 'space-lane' || dressing === 'space') return 'space'
  if (dressing === 'jungle') return 'jungle'
  if (dressing === 'snow') return 'snow'
  if (dressing === 'casino') return 'casino'
  if (dressing === 'chase-street' || dressing === 'street' || dressing === 'drive-city' || dressing === 'drive-coast' || dressing === 'drive-tunnel') return 'city'
  if (dressing === 'cafe') return 'street'
  if (dressing === 'treadmill') return 'stage'
  return 'studio'
}

export function templateSetting(id: Scene3DTemplateId): TemplateSetting {
  return settingFromDressing(applyScene3DTemplate(id).dressing)
}

export function filterScene3DTemplates(input: {
  category: 'all' | Scene3DTemplateCategory
  setting: 'all' | TemplateSetting
  query: string
  locale: 'en' | 'es'
  titleOf: (id: Scene3DTemplateId) => string
}): Scene3DTemplate[] {
  const needle = input.query.trim().toLocaleLowerCase()
  return SCENE3D_TEMPLATES.filter(item => {
    if (input.category !== 'all' && TEMPLATE_CATEGORIES[item.id] !== input.category) return false
    if (input.setting !== 'all' && templateSetting(item.id) !== input.setting) return false
    if (!needle) return true
    const card = campaignCard(item.id, input.locale) ?? actionCard(item.id, input.locale)
    const haystack = `${input.titleOf(item.id)} ${card?.description ?? ''} ${card?.requirements.join(' ') ?? ''} ${item.id} ${templateSetting(item.id)}`
    return haystack.toLocaleLowerCase().includes(needle)
  })
}

export function settingsIn(templates: readonly Scene3DTemplate[]): TemplateSetting[] {
  const seen = new Set<TemplateSetting>()
  for (const item of templates) seen.add(templateSetting(item.id))
  return TEMPLATE_SETTINGS.filter(setting => seen.has(setting))
}
