import { buildTextTemplate, parseKineticTexts, TEXT_TEMPLATES } from '../../lib/kineticText'
import { randomUuid } from '../../lib/uuid'
import { FX_CATALOG, parseSceneFx } from '../sceneFx/types'
import { createWorldSfx, parseWorldSfx, WORLD_SFX_KINDS, type WorldSfxKind } from '../sceneFx/world'
import type { Scene3DDocument } from './types'
import type { AddPickerItem } from './addPickerCatalog'

/** The document change for one picked effect or text. Demos and showcases return null. */
export function applyAddPicker(document: Scene3DDocument, item: AddPickerItem): Scene3DDocument | null {
  const action = item.action
  if (action.type === 'world') return withWorld(document, action.kind)
  if (action.type === 'overlay') return withOverlay(document, action.kind)
  if (action.type === 'text') return withText(document, action.templateId)
  return null
}

export function dispatchAddPicker(
  item: AddPickerItem,
  hooks: {
    applyScene: (updater: (current: Scene3DDocument) => Scene3DDocument) => void
    onDemo: (demo: 'depth' | 'duel' | 'mixed') => void
    onShowcase: (showcase: 'all' | 'anime' | 'retro') => void
  },
) {
  const action = item.action
  if (action.type === 'world-demo') { hooks.onDemo(action.demo); return }
  if (action.type === 'showcase') { hooks.onShowcase(action.showcase); return }
  hooks.applyScene(current => applyAddPicker(current, item) ?? current)
}

function withWorld(document: Scene3DDocument, kind: string): Scene3DDocument | null {
  if (!(WORLD_SFX_KINDS as readonly string[]).includes(kind)) return null
  const taken = (document.worldSfx ?? []).map(cue => cue.id)
  const cue = createWorldSfx(kind as WorldSfxKind, document.duration, taken)
  return { ...document, worldSfx: parseWorldSfx([...(document.worldSfx ?? []), cue]) }
}

function withOverlay(document: Scene3DDocument, kind: string): Scene3DDocument | null {
  if (!FX_CATALOG.some(item => item.id === kind)) return null
  const id = `fx-${Date.now().toString(36)}`
  return {
    ...document,
    sfx: parseSceneFx([...(document.sfx ?? []), { id, kind, start: 0, end: Math.min(3, document.duration) }]),
  }
}

function withText(document: Scene3DDocument, templateId: string): Scene3DDocument | null {
  const template = TEXT_TEMPLATES.find(item => item.id === templateId)
  if (!template) return null
  const values = Object.fromEntries(template.fields.map(field => [field.key, field.default]))
  const frame = { start: 0, duration: Math.min(4, document.duration), width: document.width, height: document.height }
  const cues = buildTextTemplate(template.id, values, frame).map(cue => ({ ...cue, id: randomUuid() }))
  return { ...document, texts: parseKineticTexts([...(document.texts ?? []), ...cues]) }
}
