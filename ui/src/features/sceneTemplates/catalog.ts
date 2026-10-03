/**
 * Candidate-only scene templates for the Video3D review gallery.
 *
 * Data lives in app/shared/scene_templates.json. This module is the derived
 * view the gallery, composer and compilers already import. Adding a candidate
 * here must not add it to the recipe grammar or approve it.
 */

import sceneTemplateCatalog from '../../../../app/shared/scene_templates.json' with { type: 'json' }

export const CATALOG_VERSION = '2026-09-review-1' as const
export const EXPANDED_CATALOG_VERSION = '2026-09-music-motion-1' as const

export type TemplateFamily = 'cinema' | 'music' | 'space'

export type TemplateSlotName = 'hero' | 'plate' | 'prop' | 'foreground' | 'subject_1' | 'subject_2' | 'background' | 'prop_1'

export type SceneTemplateSlot = {
  readonly id: TemplateSlotName
  readonly required: boolean
  readonly kinds: readonly ('image' | 'model3d')[]
  readonly description: string
}

export type SceneTemplateDefinition = {
  readonly id: string
  readonly version: 1
  readonly status: 'candidate'
  readonly family: TemplateFamily
  readonly title: string
  readonly description: string
  readonly slots: readonly SceneTemplateSlot[]
  readonly limits: readonly string[]
  readonly promptExample: string
  readonly defaultDuration: number
  readonly motionIntensity?: 'moderate' | 'high'
  readonly rhythmic?: boolean
}

const FAMILIES = ['cinema', 'music', 'space'] as const
const GROUPS = ['candidate', 'video2d', 'music-motion'] as const
const SLOT_IDS = ['hero', 'plate', 'prop', 'foreground', 'subject_1', 'subject_2', 'background', 'prop_1'] as const
const SLOT_TYPES = ['image', 'model3d'] as const
const INTENSITIES = ['moderate', 'high'] as const

type RawSlot = { id: string; types: string[]; required: boolean; description: string }
type RawEntry = {
  id: string
  family: string
  reviewStatus: string
  visualIntent: string
  title: string
  version: number
  slots: RawSlot[]
  limits: string[]
  example: string
  defaultDuration: number
  group: string
  motionIntensity?: string
}

const known = <T extends string>(values: readonly T[], value: string): value is T =>
  (values as readonly string[]).includes(value)

function sceneTemplate(entry: RawEntry): SceneTemplateDefinition {
  if (entry.reviewStatus !== 'candidate' || entry.version !== 1 || !known(FAMILIES, entry.family) || !known(GROUPS, entry.group)) {
    throw new Error(`Scene template ${entry.id} is not a version 1 candidate.`)
  }
  if (entry.motionIntensity !== undefined && !known(INTENSITIES, entry.motionIntensity)) {
    throw new Error(`Scene template ${entry.id} has an unknown motion intensity.`)
  }
  return {
    id: entry.id,
    version: 1,
    status: entry.reviewStatus,
    family: entry.family,
    title: entry.title,
    description: entry.visualIntent,
    slots: entry.slots.map(slot => {
      if (!known(SLOT_IDS, slot.id)) throw new Error(`Scene template ${entry.id} has an unknown slot.`)
      return {
        id: slot.id,
        required: slot.required,
        kinds: slot.types.map(type => {
          if (!known(SLOT_TYPES, type)) throw new Error(`Scene template ${entry.id} has an unknown slot.`)
          return type
        }),
        description: slot.description,
      }
    }),
    limits: entry.limits,
    promptExample: entry.example,
    defaultDuration: entry.defaultDuration,
    ...(entry.motionIntensity ? { motionIntensity: entry.motionIntensity } : {}),
  }
}

if (sceneTemplateCatalog.catalogVersion !== CATALOG_VERSION || sceneTemplateCatalog.expandedCatalogVersion !== EXPANDED_CATALOG_VERSION) {
  throw new Error('Unexpected scene template catalog version.')
}

const rawEntries = sceneTemplateCatalog.entries as RawEntry[]
for (const entry of rawEntries) {
  if (!known(GROUPS, entry.group)) throw new Error(`Scene template ${entry.id} has an unknown group.`)
}
const templatesIn = (group: (typeof GROUPS)[number]) => rawEntries.filter(entry => entry.group === group).map(sceneTemplate)

export const CANDIDATE_SCENE_TEMPLATES = templatesIn('candidate')
export const VIDEO2D_SCENE_TEMPLATES = templatesIn('video2d')
export const MUSIC_MOTION_TEMPLATES = templatesIn('music-motion')

/** Original references stay versioned separately: never rewrite their hashes or
 * infer that a new choreography has an approved reference because it compiles. */
export const ALL_SCENE_TEMPLATES: readonly SceneTemplateDefinition[] = [...CANDIDATE_SCENE_TEMPLATES, ...MUSIC_MOTION_TEMPLATES]

// Membership is explicit: the legacy catalogue contains a few `music-*`
// IDs of its own, and a slot name alone must not move one of those templates
// into the expanded review version.
const EXPANDED_TEMPLATE_IDS = new Set(MUSIC_MOTION_TEMPLATES.map(template => template.id))

export function templateCatalogVersion(template: SceneTemplateDefinition): string {
  return EXPANDED_TEMPLATE_IDS.has(template.id) ? EXPANDED_CATALOG_VERSION : CATALOG_VERSION
}

export function getCandidateSceneTemplate(id: string): SceneTemplateDefinition {
  const template = ALL_SCENE_TEMPLATES.find(candidate => candidate.id === id)
  if (!template) {
    throw new Error(`Unknown candidate scene template: ${id}`)
  }
  return template
}
