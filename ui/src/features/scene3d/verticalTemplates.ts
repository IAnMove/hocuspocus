import {
  buildCastPackDocument, castPackCategories, castPackRows, type CastPackApplyOptions, type CastPackCardCopy, type CastPackSpec,
} from './castPacks.ts'
import { VERTICAL_DIALOGUE_SPECS } from './verticalDialogueSpecs.ts'
import { VERTICAL_TALK_SPECS } from './verticalTalkSpecs.ts'
import { VERTICAL_TEMPLATE_IDS, type VerticalTemplateId } from './verticalTemplateIds.ts'
import type { Scene3DDocument } from './types.ts'

export { VERTICAL_TEMPLATE_IDS, type VerticalTemplateId }

/** Dialogue and talk cards drawn for 9:16: the camera is authored for the tall frame, never adapted from a landscape one. */
const SPECS: Record<VerticalTemplateId, CastPackSpec> = { ...VERTICAL_DIALOGUE_SPECS, ...VERTICAL_TALK_SPECS }

export function isVerticalTemplateId(id: string): id is VerticalTemplateId {
  return (VERTICAL_TEMPLATE_IDS as readonly string[]).includes(id)
}

export const VERTICAL_TEMPLATES = castPackRows(VERTICAL_TEMPLATE_IDS, SPECS)
export const VERTICAL_CATEGORIES = castPackCategories(VERTICAL_TEMPLATE_IDS, SPECS)

export function applyVerticalTemplate(id: string, options: CastPackApplyOptions = {}): Scene3DDocument | null {
  if (!isVerticalTemplateId(id)) return null
  return buildCastPackDocument(SPECS[id], id, options)
}

export function verticalTemplateDocument(id: string): Scene3DDocument | null {
  return applyVerticalTemplate(id)
}

export function verticalCard(id: string, locale: 'en' | 'es' = 'en'): CastPackCardCopy | undefined {
  if (!isVerticalTemplateId(id)) return undefined
  return SPECS[id].copy[locale]
}

export function verticalAliases(id: string): Record<string, string> {
  return isVerticalTemplateId(id) ? { ...SPECS[id].aliases } : {}
}
