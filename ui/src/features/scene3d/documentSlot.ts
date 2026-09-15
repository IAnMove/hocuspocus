import { parseAppearance } from './cinematicSettings'
import { parseClipPlayback, parseMotion } from './performance.ts'
import { parseSpeech } from './speech/track'
import { parseCharacterKitRef, parseCharacterVoice } from '../../lib/characterVoice'
import { parseMediaScreen } from './mediaScreen.ts'
import { parseScene3DLoop } from './backdrop.ts'
import { durableScene3DSourceUrl, parseScene3DSourceRef } from './slotSource.ts'
import type { Scene3DDressing, Scene3DSlot } from './types.ts'

const DRESSINGS = new Set<Scene3DDressing>(['street', 'space', 'treadmill', 'cafe', 'drive-city', 'drive-coast', 'drive-tunnel', 'citadel', 'workshop', 'chase-street', 'retro-lab', 'observatory', 'broadcast-plaza', 'open-sea', 'lunar', 'rooftop', 'hangar', 'desert', 'train', 'space-lane', 'jungle', 'snow', 'casino'])
export const parseDressing = (value?: Scene3DDressing) => DRESSINGS.has(value!) ? value : undefined

function textureRepeat(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(16, Math.max(1, value)) : undefined
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
    speech: slot.media === 'image' || slot.media === 'screen' ? undefined : parseSpeech(slot.speech),
    media: slot.media === 'image' ? 'image' : slot.media === 'screen' ? 'screen' : 'model3d', screen: parseMediaScreen(slot.screen),
    loop: parseScene3DLoop(slot.loop), clipPlayback: parseClipPlayback(slot.clipPlayback), motion: parseMotion(slot.motion),
    appearance: parseAppearance(slot.appearance),
    surface: slot.surface === 'environment' || slot.surface === 'floor' || slot.surface === 'wall' ? slot.surface : undefined,
    grounded: slot.grounded === true, textureRepeat: textureRepeat(slot.textureRepeat),
    performance: slot.performance === 'typing' || slot.performance === 'idle' ? slot.performance : undefined,
  }
}
