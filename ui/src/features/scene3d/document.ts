import { parseEnvironment } from './cinematicSettings'
import { parseSceneFx } from '../sceneFx/types'
import { parseWorldSfx } from '../sceneFx/world'
import { parseKineticTexts } from '../../lib/kineticText.ts'
import { parseSoundtrack } from './speech/track'
import { validScene3DShape } from './documentValidation.ts'
import { scene3dPlaybackSpeed } from './clock.ts'
import { reviewClipNumber } from './performance.ts'
import { normalizeScene3DSlot, parseDressing } from './documentSlot.ts'
import { SCENE3D_TEMPLATE_IDS, type Scene3DDocument, type Scene3DSlot, type Scene3DTemplateId } from './types.ts'

const SLOT_COLORS: Record<string, [number, number, number]> = {
  subject_1: [40, 140, 220],
  subject_2: [220, 90, 70],
  background: [60, 60, 70],
  prop: [200, 180, 60],
}

export function scene3dSlotColor(slot: Scene3DSlot['slot']): [number, number, number] {
  return SLOT_COLORS[slot] ?? [180, 180, 180]
}

export function createDefaultScene3DDocument(): Scene3DDocument {
  return {
    version: 1,
    units: 'meters',
    up: 'y',
    width: 1280,
    height: 720,
    fps: 30,
    duration: 4,
    templateId: 'two-shot',
    camera: {
      family: 'establishment',
      eye: [0, 1.6, 4.2],
      look: [0, 1, 0],
      fov: 50,
      orbitRadius: 4.2,
      orbitHeight: 1.6,
      orbitTurns: 1,
    },
    light: {
      kind: 'directional',
      direction: [-0.35, -1, -0.25],
      intensity: 1.15,
      color: '#fff4e5',
    },
    slots: [
      {
        id: 'subject_1',
        slot: 'subject_1',
        position: [-0.85, 0, 0],
        rotationY: 0.35,
        scale: 1,
        sourceUrl: '',
        media: 'model3d',
        clip: null,
      },
      {
        id: 'subject_2',
        slot: 'subject_2',
        position: [0.85, 0, 0],
        rotationY: -0.35,
        scale: 1,
        sourceUrl: '',
        media: 'model3d',
        clip: null,
      },
    ],
  }
}

export function cloneScene3DDocument(document: Scene3DDocument): Scene3DDocument {
  return structuredClone(document)
}

function validProduction(p: Scene3DDocument['production']) {
  if (p === undefined) return true
  return !!p && ['song', 'dialogue', 'episode', 'trailer'].includes(p.kind)
    && typeof p.title === 'string' && p.title.length <= 500
    && typeof p.workspace === 'string' && !!p.workspace && p.workspace.length <= 120
    && (p.sourceId === undefined || (typeof p.sourceId === 'string' && p.sourceId.length <= 300))
}
function knownTemplateId(value: unknown): Scene3DTemplateId {
  return typeof value === 'string' && (SCENE3D_TEMPLATE_IDS as readonly string[]).includes(value) ? value as Scene3DTemplateId : 'two-shot'
}

function parseWorkshopScreen(value: unknown) {
  return value === 'error' || value === 'success' ? value : undefined
}
export function parseScene3DDocument(raw: unknown): Scene3DDocument | null {
  if (!raw || typeof raw !== 'object') return null
  const value = raw as Partial<Scene3DDocument>
  if (value.version !== 1 || value.units !== 'meters' || value.up !== 'y') return null
  if (!Array.isArray(value.slots) || !value.camera || !value.light) return null
  if (!validScene3DShape(value)) return null
  let slots: Scene3DSlot[]
  let soundtrack: Scene3DDocument['soundtrack']
  try { slots = value.slots.map(normalizeScene3DSlot); soundtrack = parseSoundtrack(value.soundtrack) } catch { return null }
  if (!validProduction(value.production)) return null
  const templateId = knownTemplateId(value.templateId)
  const dressing = parseDressing(value.dressing)
  const workshopScreen = parseWorkshopScreen(value.workshopScreen)
  const worldSfx = parseWorldSfx(value.worldSfx)
  return { ...value, environment: parseEnvironment(value.environment), ...(soundtrack !== undefined ? { soundtrack } : {}), workshopScreen, sfx: parseSceneFx(value.sfx), ...(worldSfx.length ? { worldSfx } : {}), texts: parseKineticTexts(value.texts), slots, templateId, dressing, clipNumber: reviewClipNumber(value.clipNumber), playbackSpeed: scene3dPlaybackSpeed(value.playbackSpeed) } as Scene3DDocument
}
