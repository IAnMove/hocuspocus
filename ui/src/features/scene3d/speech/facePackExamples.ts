import { defaultModelScreen } from '../mediaScreen.ts'
import type { Scene3DSlot, Scene3DSlotId, Scene3DSourceRef, Vec3 } from '../types.ts'
import { defaultSpeech, type ExpressionCue, type MouthCue, type Scene3DSpeech, type Scene3DSoundtrack } from './types'

export const FACE_PACK_GLB = '/examples/tv-head-humanoid.glb'
export const FACE_PACK_AUDIO_URL = '/examples/face-pack/neutral-vowels.wav'
export const FACE_PACK_IDS = [
  'tv', 'skull', 'voxel', 'anime', 'cubeskull',
  'felt', 'clay', 'pixel', 'porcelain', 'cat', 'oni', 'stencil', 'alien',
  'pumpkin', 'ice', 'mushroom', 'vector', 'halftone', 'steampunk', 'gummy',
] as const
export type FacePackId = typeof FACE_PACK_IDS[number]

const bundled = (filename: string, url: string): Scene3DSourceRef => (
  { workspaceId: 'bundled', filename, url }
)

export const FACE_PACK_AUDIO = bundled('neutral-vowels.wav', FACE_PACK_AUDIO_URL)
export const FACE_PACK_SOUNDTRACK: Scene3DSoundtrack[] = [
  { id: 'neutral-vowels', audio: FACE_PACK_AUDIO, start: 0, offset: 0, gain: 0.9, end: 8 },
]

export const FACE_PACKS: Record<FacePackId, { id: FacePackId; url: string; source: Scene3DSourceRef; visemes: string }> = Object.fromEntries(
  FACE_PACK_IDS.map(id => {
    const file = `${id}-pack.png`
    const vis = `${id}-visemes.png`
    return [id, { id, url: `/examples/face-pack/${file}`, source: bundled(file, `/examples/face-pack/${file}`), visemes: `/examples/face-pack/${vis}` }]
  }),
) as Record<FacePackId, { id: FacePackId; url: string; source: Scene3DSourceRef; visemes: string }>

const LEAD_MOUTH: MouthCue[] = [
  { start: 0, end: 0.35, viseme: 'rest' },
  { start: 0.35, end: 0.85, viseme: 'A' },
  { start: 0.85, end: 1.05, viseme: 'rest' },
  { start: 1.05, end: 1.55, viseme: 'E' },
  { start: 1.55, end: 1.75, viseme: 'rest' },
  { start: 1.75, end: 2.25, viseme: 'I' },
  { start: 2.25, end: 2.45, viseme: 'rest' },
  { start: 2.45, end: 2.95, viseme: 'O' },
  { start: 2.95, end: 3.15, viseme: 'rest' },
  { start: 3.15, end: 3.65, viseme: 'U' },
  { start: 3.65, end: 8, viseme: 'rest' },
]

const REPLY_MOUTH: MouthCue[] = [
  { start: 0, end: 4.35, viseme: 'rest' },
  { start: 4.35, end: 4.85, viseme: 'A' },
  { start: 4.85, end: 5.05, viseme: 'rest' },
  { start: 5.05, end: 5.55, viseme: 'E' },
  { start: 5.55, end: 5.75, viseme: 'rest' },
  { start: 5.75, end: 6.25, viseme: 'I' },
  { start: 6.25, end: 6.45, viseme: 'rest' },
  { start: 6.45, end: 6.95, viseme: 'O' },
  { start: 6.95, end: 7.15, viseme: 'rest' },
  { start: 7.15, end: 7.65, viseme: 'U' },
  { start: 7.65, end: 8, viseme: 'rest' },
]

/** One expression for the whole turn; visemes change underneath. */
const LEAD_FACE: ExpressionCue[] = [
  { start: 0, end: 0.35, expression: 'neutral' },
  { start: 0.35, end: 3.65, expression: 'happy' },
  { start: 3.65, end: 8, expression: 'neutral' },
]

const REPLY_FACE: ExpressionCue[] = [
  { start: 0, end: 4.35, expression: 'neutral' },
  { start: 4.35, end: 7.65, expression: 'angry' },
  { start: 7.65, end: 8, expression: 'neutral' },
]

export function facePackIdOf(url: string | undefined): FacePackId | undefined {
  return FACE_PACK_IDS.find(id => FACE_PACKS[id].url === url || FACE_PACKS[id].source.url === url)
}

function demoSpeech(pack: Scene3DSourceRef, role: 'lead' | 'reply'): Scene3DSpeech {
  return {
    ...defaultSpeech(),
    enabled: true,
    audible: false,
    driver: 'imported',
    start: 0,
    offset: 0,
    end: 8,
    gain: 1,
    blink: false,
    eyes: false,
    facePack: pack,
    cues: role === 'lead' ? LEAD_MOUTH : REPLY_MOUTH,
    expressionCues: role === 'lead' ? LEAD_FACE : REPLY_FACE,
  }
}

export function applyBundledFacePack(speech: Scene3DSpeech, id: FacePackId): Scene3DSpeech {
  const pack = FACE_PACKS[id].source
  return {
    ...speech,
    enabled: true,
    blink: false,
    eyes: false,
    facePack: pack,
    cues: speech.cues.length ? speech.cues : LEAD_MOUTH,
    expressionCues: speech.expressionCues ?? LEAD_FACE,
  }
}

export function talkingScreen(id: FacePackId) {
  const pack = FACE_PACKS[id]
  return {
    ...defaultModelScreen(['headfront', 'Head', 'tv_frame']),
    sourceUrl: pack.url,
    sourceRef: pack.source,
    media: 'image' as const,
    fit: 'cover' as const,
    pitch: 0,
    yaw: 0,
    roll: 0,
    offset: [0, 0, 0.03] as [number, number, number],
    width: 0.30,
    height: 0.22,
  }
}

export function talkingMascot(
  id: string,
  slot: Scene3DSlotId,
  position: Vec3,
  kind: FacePackId,
  patch: Partial<Scene3DSlot> = {},
): Scene3DSlot {
  const pack = FACE_PACKS[kind]
  const role = patch.speech ? 'lead' : (id === 'subject_2' ? 'reply' : 'lead')
  return {
    id,
    slot,
    media: 'model3d',
    sourceUrl: FACE_PACK_GLB,
    clip: { index: 1, name: 'Idle' },
    clipPlayback: { speed: 1, start: 0, loop: true },
    position,
    rotationY: 0,
    scale: 1,
    grounded: true,
    screen: talkingScreen(kind),
    speech: demoSpeech(pack.source, role),
    ...patch,
  }
}
