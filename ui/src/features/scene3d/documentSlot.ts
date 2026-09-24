import { parseAppearance } from './cinematicSettings'
import { parseImageLook } from './imageLook'
import { parseClipPlayback, parseMotion } from './performance.ts'
import { parseSpeech } from './speech/track'
import { parseCharacterKitRef, parseCharacterVoice } from '../../lib/characterVoice'
import { parseMediaScreen } from './mediaScreen.ts'
import { parseScene3DLoop } from './backdrop.ts'
import { durableScene3DSourceUrl, parseScene3DSourceRef } from './slotSource.ts'
import type { Scene3DDressing, Scene3DSlot } from './types.ts'

const DRESSINGS = new Set<Scene3DDressing>(['street', 'space', 'treadmill', 'cafe', 'drive-city', 'drive-coast', 'drive-tunnel', 'citadel', 'workshop', 'chase-street', 'retro-lab', 'observatory', 'broadcast-plaza', 'open-sea', 'lunar', 'rooftop', 'hangar', 'desert', 'train', 'space-lane', 'jungle', 'snow', 'casino', 'pixel-lake', 'pixel-peaks', 'pixel-gallery', 'pixel-city', 'pixel-desert', 'pixel-coast', 'pixel-forest', 'pixel-viaduct', 'pixel-volcano', 'pixel-drivein', 'pixel-garden', 'pixel-reef', 'pixel-valley', 'pixel-fair', 'pixel-village', 'pixel-falls', 'pixel-orbit', 'pixel-tulips', 'pixel-alley', 'pixel-castle', 'pixel-beach', 'pixel-lanterns', 'pixel-window', 'pixel-express', 'pixel-daycycle', 'pixel-eclipse', 'pixel-seasons', 'pixel-cathedral', 'pixel-koi', 'pixel-caravan', 'pixel-synthwave', 'pixel-monsoon', 'pixel-marsh', 'pixel-launch', 'pixel-grotto'])
export const parseDressing = (value?: Scene3DDressing) => DRESSINGS.has(value!) ? value : undefined

function textureRepeat(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(16, Math.max(1, value)) : undefined
}

function parseSlotMedia(media: Scene3DSlot['media']): Scene3DSlot['media'] {
  return media === 'image' || media === 'screen' ? media : 'model3d'
}

function parseSurface(surface: Scene3DSlot['surface']) {
  return surface === 'environment' || surface === 'floor' || surface === 'wall' || surface === 'cutout' ? surface : undefined
}

function parsePerformance(performance: Scene3DSlot['performance']) {
  return performance === 'typing' || performance === 'idle' ? performance : undefined
}

function validCharacterIdentity(value: NonNullable<Scene3DSlot['character']>) {
  return value && typeof value.id === 'string' && !!value.id && value.id.length <= 160
    && typeof value.name === 'string' && value.name.length <= 300
}
function normalizeCharacter(character: Scene3DSlot['character']) {
  if (character === undefined) return undefined
  if (!validCharacterIdentity(character)) throw new Error('Invalid character identity.')
  if (character.libraryRevision !== undefined && (!Number.isInteger(character.libraryRevision) || character.libraryRevision < 0)) throw new Error('Invalid character revision.')
  return { id: character.id, name: character.name,
    ...(character.kitRef !== undefined ? { kitRef: parseCharacterKitRef(character.kitRef) } : {}),
    ...(character.voice !== undefined ? { voice: parseCharacterVoice(character.voice) } : {}),
    ...(character.libraryRevision !== undefined ? { libraryRevision: character.libraryRevision } : {}) }
}
export function normalizeScene3DSlot(slot: Scene3DSlot): Scene3DSlot {
  const sourceUrl = durableScene3DSourceUrl(typeof slot.sourceUrl === 'string' ? slot.sourceUrl : '')
  const sourceRef = parseScene3DSourceRef(slot.sourceRef)
  return {
    ...slot, sourceUrl, sourceRef: sourceUrl && sourceRef ? sourceRef : undefined,
    character: normalizeCharacter(slot.character),
    speech: parseSlotMedia(slot.media) === 'model3d' ? parseSpeech(slot.speech) : undefined,
    media: parseSlotMedia(slot.media), screen: parseMediaScreen(slot.screen),
    loop: parseScene3DLoop(slot.loop), clipPlayback: parseClipPlayback(slot.clipPlayback), motion: parseMotion(slot.motion),
    appearance: parseAppearance(slot.appearance),
    imageLook: slot.media === 'image' && slot.surface === 'cutout' ? parseImageLook(slot.imageLook) : undefined,
    surface: parseSurface(slot.surface),
    grounded: slot.grounded === true, textureRepeat: textureRepeat(slot.textureRepeat),
    performance: parsePerformance(slot.performance),
  }
}
