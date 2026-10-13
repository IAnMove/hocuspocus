/**
 * Video 2D scene templates: the 41 cards of app/shared/scene_templates.json.
 *
 * Data lives in the JSON; this module is the checked view the gallery, composer and compilers import. A merged id
 * is an alias (its card plus a control preset) and a retired id names what to use instead
 * (docs/development/VIDEO2D_TEMPLATE_MODEL.md). Adding a card here does not approve it.
 */

import sceneTemplateCatalog from '../../../../app/shared/scene_templates.json' with { type: 'json' }
// The i18next instance src/i18n initializes at app start. E2E specs load this module in Node,
// where src/i18n's locale JSON cannot load, so it is not imported here.
import i18n from 'i18next'
import { TemplateError } from './templateErrors'

export const CATALOG_VERSION = '2026-09-review-1' as const
export const EXPANDED_CATALOG_VERSION = '2026-09-music-motion-1' as const

export type TemplateFamily = 'cinema' | 'music' | 'space'
export type TemplateGroup = 'candidate' | 'video2d' | 'music-motion'
export type TemplateSlotName = 'subject_1' | 'subject_2' | 'background' | 'prop_1' | 'prop_2' | 'foreground'
/** Names from before the 2026-10-12 slot vocabulary; accepted at every entry and translated once. */
export type LegacySlotName = 'hero' | 'plate' | 'prop'
export type TemplateAssetKind = 'image' | 'model3d' | 'video'
export type ReviewStatus = 'candidate' | 'approved'

export type SceneTemplateSlot = {
  readonly id: TemplateSlotName
  readonly required: boolean
  /** Required only while every listed control has the listed value. */
  readonly requiredWhen?: Readonly<Record<string, string>>
  readonly kinds: readonly TemplateAssetKind[]
  readonly description: string
}

export type NumberControlSpec = { readonly kind: 'number'; readonly min: number; readonly max: number; readonly default: number; readonly exposed: boolean }
export type ChoiceControlSpec = { readonly kind: 'choice'; readonly options: readonly string[]; readonly default: string; readonly exposed: boolean }
export type TextControlSpec = { readonly kind: 'text'; readonly maxLength: number; readonly default: string; readonly exposed: boolean }
export type ControlSpec = NumberControlSpec | ChoiceControlSpec | TextControlSpec
export type ControlValue = number | string

export type SceneTemplateDefinition = {
  readonly id: string
  readonly version: 1
  readonly status: ReviewStatus
  readonly family: TemplateFamily
  readonly group: TemplateGroup
  readonly title: string
  readonly description: string
  readonly slots: readonly SceneTemplateSlot[]
  readonly controls: Readonly<Record<string, ControlSpec>>
  readonly limits: readonly string[]
  readonly promptExample: string
  readonly defaultDuration: number
  readonly motionIntensity?: 'moderate' | 'high'
  /** Narrative templates (ui/src/lib/sceneNarrative.ts) that cover the same intent; such a card lives on that shelf. */
  readonly twins: readonly string[]
  /** Old slot names this card translates, after the card's own overrides. */
  readonly slotAliases: Readonly<Record<string, TemplateSlotName>>
}

export type SceneTemplateAlias = { readonly card: string; readonly preset: Readonly<Record<string, ControlValue>> }
export type RetiredSceneTemplate = { readonly useInstead: readonly string[]; readonly note: string }

const FAMILIES = ['cinema', 'music', 'space'] as const
const GROUPS = ['candidate', 'video2d', 'music-motion'] as const
const STATUSES = ['candidate', 'approved'] as const
const SLOT_IDS = ['subject_1', 'subject_2', 'background', 'prop_1', 'prop_2', 'foreground'] as const
const LEGACY_SLOT_IDS = ['hero', 'plate', 'prop', 'foreground'] as const
const SLOT_TYPES = ['image', 'model3d', 'video'] as const
const INTENSITIES = ['moderate', 'high'] as const

type RawSlot = { id: string; types: string[]; required: boolean; requiredWhen?: Record<string, string>; description: string }
type RawControl = { min?: unknown; max?: unknown; default?: unknown; options?: unknown; text?: unknown; maxLength?: unknown; exposed?: unknown }
type RawEntry = {
  id: string
  family: string
  reviewStatus: string
  visualIntent: string
  title: string
  version: number
  slots: RawSlot[]
  controls: Record<string, RawControl>
  limits: string[]
  example: string
  defaultDuration: number
  group: string
  motionIntensity?: string
  twins?: string[]
  slotAliases?: Record<string, string>
}
type RawCatalog = {
  catalogVersion: string
  expandedCatalogVersion: string
  slotAliases: Record<string, string>
  aliases: Record<string, { card: string; preset: Record<string, ControlValue> }>
  retired: Record<string, { useInstead: string[]; note: string }>
  entries: RawEntry[]
}

const known = <T extends string>(values: readonly T[], value: string): value is T =>
  (values as readonly string[]).includes(value)
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

function numberControl(raw: RawControl, exposed: boolean): NumberControlSpec | undefined {
  const { min, max } = raw
  const value = raw.default
  if (!finite(min) || !finite(max) || !finite(value) || min > value || value > max) return undefined
  return { kind: 'number', min, max, default: value, exposed }
}

function choiceControl(raw: RawControl, exposed: boolean): ChoiceControlSpec | undefined {
  const options = raw.options
  if (!Array.isArray(options) || !options.length || options.some(item => typeof item !== 'string' || !item)) return undefined
  if (new Set(options).size !== options.length || typeof raw.default !== 'string' || !options.includes(raw.default)) return undefined
  return { kind: 'choice', options: options as string[], default: raw.default, exposed }
}

function textControl(raw: RawControl, exposed: boolean): TextControlSpec | undefined {
  const { maxLength } = raw
  if (!Number.isInteger(maxLength) || (maxLength as number) < 1 || typeof raw.default !== 'string') return undefined
  if ([...raw.default].length > (maxLength as number)) return undefined
  return { kind: 'text', maxLength: maxLength as number, default: raw.default, exposed }
}

function controlSpec(id: string, key: string, raw: RawControl): ControlSpec {
  const exposed = raw.exposed === true
  const spec = raw.options !== undefined ? choiceControl(raw, exposed) : raw.text === true ? textControl(raw, exposed) : numberControl(raw, exposed)
  if (!spec) throw new Error(`Scene template ${id} has an invalid control ${key}.`)
  return spec
}

function sceneSlot(id: string, slot: RawSlot): SceneTemplateSlot {
  if (!known(SLOT_IDS, slot.id)) throw new Error(`Scene template ${id} has an unknown slot.`)
  return {
    id: slot.id,
    required: slot.required,
    ...(slot.requiredWhen ? { requiredWhen: { ...slot.requiredWhen } } : {}),
    kinds: slot.types.map(type => {
      if (!known(SLOT_TYPES, type)) throw new Error(`Scene template ${id} has an unknown slot.`)
      return type
    }),
    description: slot.description,
  }
}

function slotAliases(id: string, defaults: Record<string, string>, own: Record<string, string> = {}) {
  const merged = { ...defaults, ...own }
  for (const [legacy, slot] of Object.entries(merged)) {
    if (!known(LEGACY_SLOT_IDS, legacy) || !known(SLOT_IDS, slot)) throw new Error(`Scene template ${id} has an unknown slot alias.`)
  }
  return merged as Record<string, TemplateSlotName>
}

function sceneTemplate(entry: RawEntry, defaults: Record<string, string>): SceneTemplateDefinition {
  if (!known(STATUSES, entry.reviewStatus) || entry.version !== 1 || !known(FAMILIES, entry.family) || !known(GROUPS, entry.group)) {
    throw new Error(`Scene template ${entry.id} is not a version 1 candidate or approved card.`)
  }
  if (entry.motionIntensity !== undefined && !known(INTENSITIES, entry.motionIntensity)) {
    throw new Error(`Scene template ${entry.id} has an unknown motion intensity.`)
  }
  const controls = Object.fromEntries(Object.entries(entry.controls).map(([key, raw]) => [key, controlSpec(entry.id, key, raw)]))
  for (const slot of entry.slots) {
    for (const [key, value] of Object.entries(slot.requiredWhen ?? {})) {
      const spec = controls[key]
      if (spec?.kind !== 'choice' || !spec.options.includes(value)) throw new Error(`Scene template ${entry.id} has an invalid requiredWhen.`)
    }
  }
  return {
    id: entry.id,
    version: 1,
    status: entry.reviewStatus,
    family: entry.family,
    group: entry.group,
    title: entry.title,
    description: entry.visualIntent,
    slots: entry.slots.map(slot => sceneSlot(entry.id, slot)),
    controls,
    limits: entry.limits,
    promptExample: entry.example,
    defaultDuration: entry.defaultDuration,
    ...(entry.motionIntensity ? { motionIntensity: entry.motionIntensity } : {}),
    twins: entry.twins ?? [],
    slotAliases: slotAliases(entry.id, defaults, entry.slotAliases),
  }
}

const rawCatalog = sceneTemplateCatalog as unknown as RawCatalog
if (rawCatalog.catalogVersion !== CATALOG_VERSION || rawCatalog.expandedCatalogVersion !== EXPANDED_CATALOG_VERSION) {
  throw new Error('Unexpected scene template catalog version.')
}

/** Checks one JSON card as the loader does; tests use it for statuses the shipped JSON does not hold yet. */
export function parseSceneTemplateEntry(entry: unknown): SceneTemplateDefinition {
  return sceneTemplate(entry as RawEntry, rawCatalog.slotAliases)
}

const rawEntries = rawCatalog.entries
for (const entry of rawEntries) {
  if (!known(GROUPS, entry.group)) throw new Error(`Scene template ${entry.id} has an unknown group.`)
}

/** Every card in catalog order. */
export const ALL_SCENE_TEMPLATES: readonly SceneTemplateDefinition[] = rawEntries.map(entry => sceneTemplate(entry, rawCatalog.slotAliases))
const templatesIn = (group: TemplateGroup) => ALL_SCENE_TEMPLATES.filter(template => template.group === group)

/** The original grammars (coral v1 references) that survived the merges. */
export const CANDIDATE_SCENE_TEMPLATES = templatesIn('candidate')
export const VIDEO2D_SCENE_TEMPLATES = templatesIn('video2d')
export const MUSIC_MOTION_TEMPLATES = templatesIn('music-motion')
/** The «crear con mis assets» shelf: a card with narrative twins lives on the narrative grid instead. */
export const COMPOSER_SCENE_TEMPLATES = ALL_SCENE_TEMPLATES.filter(template => !template.twins.length)

const byId = new Map(ALL_SCENE_TEMPLATES.map(template => [template.id, template]))

function checkAlias(id: string, alias: SceneTemplateAlias): SceneTemplateAlias {
  const card = byId.get(alias.card)
  if (!card || byId.has(id)) throw new Error(`Scene template alias ${id} does not name one card.`)
  for (const [key, value] of Object.entries(alias.preset)) {
    const spec = card.controls[key]
    if (spec?.kind !== 'choice' || typeof value !== 'string' || !spec.options.includes(value)) throw new Error(`Scene template alias ${id} has an invalid preset.`)
  }
  return { card: alias.card, preset: { ...alias.preset } }
}

export const SCENE_TEMPLATE_ALIASES: Readonly<Record<string, SceneTemplateAlias>> = Object.fromEntries(
  Object.entries(rawCatalog.aliases).map(([id, alias]) => [id, checkAlias(id, alias)]),
)
export const RETIRED_SCENE_TEMPLATES: Readonly<Record<string, RetiredSceneTemplate>> = Object.fromEntries(
  Object.entries(rawCatalog.retired).map(([id, item]) => {
    if (byId.has(id) || id in SCENE_TEMPLATE_ALIASES || !item.useInstead.length) throw new Error(`Retired scene template ${id} is still listed.`)
    return [id, { useInstead: [...item.useInstead], note: item.note }]
  }),
)

// Membership is explicit: the original catalogue contains a few `music-*`
// IDs of its own, and a slot name alone must not move one of those templates
// into the expanded review version.
const EXPANDED_TEMPLATE_IDS = new Set(MUSIC_MOTION_TEMPLATES.map(template => template.id))

export function templateCatalogVersion(template: SceneTemplateDefinition): string {
  return EXPANDED_TEMPLATE_IDS.has(template.id) ? EXPANDED_CATALOG_VERSION : CATALOG_VERSION
}

/** One of the 41 cards by its own id; aliases and retired ids are not cards. */
export function getCandidateSceneTemplate(id: string): SceneTemplateDefinition {
  const template = byId.get(id)
  if (!template) {
    throw new Error(`Unknown candidate scene template: ${id}`)
  }
  return template
}

export type ResolvedSceneTemplate = { template: SceneTemplateDefinition; alias?: string; preset: Readonly<Record<string, ControlValue>> }

/** A card id, or an alias id that compiles as its card with the alias's control preset. */
export function resolveSceneTemplate(id: string): ResolvedSceneTemplate {
  const retired = RETIRED_SCENE_TEMPLATES[id]
  if (retired) {
    throw new TemplateError('template_retired', i18n.t('scene3d:templateCompile.retired', { id, note: retired.note }), { use_instead: [...retired.useInstead] })
  }
  const alias = SCENE_TEMPLATE_ALIASES[id]
  if (alias) return { template: getCandidateSceneTemplate(alias.card), alias: id, preset: alias.preset }
  const template = byId.get(id)
  if (!template) throw new TemplateError('template_unknown', `Unknown candidate scene template: ${id}`)
  return { template, preset: {} }
}

/** The card's slot for a new or an old slot name, or undefined when the card has no such slot. */
export function canonicalSlotName(template: SceneTemplateDefinition, name: string): TemplateSlotName | undefined {
  const slotName = template.slotAliases[name] ?? name
  return template.slots.some(slot => slot.id === slotName) ? slotName as TemplateSlotName : undefined
}

/** Translate old slot names once; two names for the same slot fail with slot_alias_conflict. */
export function canonicalBindings<T>(template: SceneTemplateDefinition, raw: Readonly<Record<string, T | undefined>>): Partial<Record<TemplateSlotName, T>> {
  const out: Partial<Record<TemplateSlotName, T>> = {}
  const named: Partial<Record<TemplateSlotName, string>> = {}
  for (const [name, value] of Object.entries(raw)) {
    if (value === undefined) continue
    const slot = canonicalSlotName(template, name)
    if (!slot) throw new TemplateError('template_bad_asset', i18n.t('scene3d:templateCompile.unknownSlot', { name }))
    if (named[slot]) throw new TemplateError('slot_alias_conflict', i18n.t('scene3d:templateCompile.sameSlot', { left: named[slot], right: name, slot }))
    named[slot] = name
    out[slot] = value
  }
  return out
}

/** Slots the card needs with these control values. */
export function requiredSlots(template: SceneTemplateDefinition, controls: Readonly<Record<string, ControlValue>>): SceneTemplateSlot[] {
  return template.slots.filter(slot => slot.required
    || (slot.requiredWhen !== undefined && Object.entries(slot.requiredWhen).every(([key, value]) => controls[key] === value)))
}
