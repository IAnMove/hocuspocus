import { NARRATIVE_SCENE_TEMPLATES } from './sceneNarrative'
import type { NarrativeSceneTemplate } from './sceneNarrative'

/**
 * The template library, reduced to what a model needs in order to *choose*
 * a template — and nothing else.
 *
 * Everything omitted here is omitted deliberately. `createScene` is a
 * function and cannot serialize at all. `title` and `description` restate
 * what the id and `visualIntent` already say. `previewPrompt` is gallery
 * copy. `evaluationCues` belong to scoring a finished shot, which happens
 * long after the choice is made — feeding them into the selection prompt
 * would only pay tokens to describe an outcome the model cannot yet see.
 *
 * That restraint is the point: every token spent describing a template the
 * request does not want makes the right one harder to find, and the
 * library is expected to grow well past the current 28 entries.
 */
export type TemplateCatalogSlot = {
  id: NarrativeSceneTemplate['assetSlots'][number]['id']
  types: NarrativeSceneTemplate['assetSlots'][number]['types']
  required: boolean
}

export type TemplateCatalogEntry = {
  id: NarrativeSceneTemplate['id']
  category: NarrativeSceneTemplate['category']
  visualIntent: string
  defaultDuration: NarrativeSceneTemplate['defaultDuration']
  controls: NarrativeSceneTemplate['controls']
  constraints: NarrativeSceneTemplate['constraints']
  slots: TemplateCatalogSlot[]
}

/** Derived on call, never cached: the library is the single source of truth. */
export const buildTemplateCatalog = (
  templates: NarrativeSceneTemplate[] = NARRATIVE_SCENE_TEMPLATES,
): TemplateCatalogEntry[] => templates.map(template => ({
  id: template.id,
  category: template.category,
  visualIntent: template.visualIntent,
  defaultDuration: template.defaultDuration,
  controls: [...template.controls],
  constraints: [...template.constraints],
  slots: template.assetSlots.map(slot => ({
    id: slot.id,
    types: [...slot.types],
    required: slot.required,
  })),
}))
