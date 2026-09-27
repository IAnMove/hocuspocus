import type { CharacterKit, CharacterKitLibrary } from '../../../lib/characterKit'
import type { Scene3DSlot } from '../types'
import { parseCharacterVoice, type CharacterKitRef } from '../../../lib/characterVoice'
import { parseScene3DSourceRef } from '../slotSource'
import { defaultSpeech } from './types'
import { faceSettings, modelDigest } from './profiles'
import { parseSpeech } from './track'

/** Resolve by canonical id, verify model bytes, then freeze an independent scene snapshot. */
export async function characterSlotPatch(kit: CharacterKit, workspace: string, revision: number, slot?: Scene3DSlot): Promise<Partial<Scene3DSlot>> {
  const model = parseScene3DSourceRef(kit.speech3d?.model)
  if (!model || !/\.glb$/i.test(model.filename)) throw new Error('This character needs a saved GLB.')
  if (await modelDigest(model.url) !== kit.speech3d?.digest) throw new Error('The character model changed. Recalibrate and save its new version.')
  // Even an uncalibrated replacement owns its appearance; only scene turns survive.
  const settings = faceSettings(parseSpeech({ ...defaultSpeech(), ...kit.speech3d.settings })!)
  return { sourceUrl: model.url, sourceRef: model, media: 'model3d', clip: null,
    character: { id: slot?.character?.id ?? slot?.id ?? kit.id, name: kit.name, kitRef: { id: kit.id, workspace },
      libraryRevision: revision, voice: parseCharacterVoice(kit.voice) },
    speech: { ...defaultSpeech(), ...slot?.speech, ...settings, face: settings.face } }
}
/** Preserve every existing 2D pose/eye/mouth asset when saving the 3D extension. */
export async function characterFromSlot(kit: CharacterKit, slot: Scene3DSlot): Promise<CharacterKit> {
  if (!slot.sourceRef || slot.sourceRef.url !== slot.sourceUrl || !/\.glb$/i.test(slot.sourceRef.filename) || !slot.speech?.face) throw new Error('Choose a saved GLB and place its mouth first.')
  return { ...kit, speech3d: { model: slot.sourceRef, digest: await modelDigest(slot.sourceUrl), settings: faceSettings(slot.speech) },
    voice: parseCharacterVoice(slot.character?.voice), updatedAt: new Date().toISOString() }
}
export const speechCharacters = (library: CharacterKitLibrary) => Object.values(library.kits).filter(kit => kit.speech3d)

/** A Story/Series 2D kit ref is not enough to open Video 3D speech. Need a GLB or a speech3d kit. */
export function speechCastIsReady(
  cast: Array<{ id: string; characterKitRef?: CharacterKitRef }>,
  models: Record<string, unknown>,
  links: Record<string, CharacterKitRef | undefined>,
  speech3dKits: CharacterKit[],
): boolean {
  if (cast.length < 1 || cast.length > 2) return false
  return cast.every(speaker => {
    if (models[speaker.id]) return true
    const ref = Object.hasOwn(links, speaker.id) ? links[speaker.id] : speaker.characterKitRef
    return Boolean(ref && speech3dKits.some(kit => kit.id === ref.id && kit.speech3d))
  })
}
