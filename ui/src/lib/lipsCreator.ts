import { createCharacterKit, type CharacterKit, type CharacterKitAsset, type CharacterMouthState } from './characterKit'
import { CHARACTER_MOUTH_STATES, MOUTH_SOUND_GROUPS, mouthStateForSound } from './characterMouthStates'
import { assertFacePatchPose } from './characterFacePatch'
import { classifyCharacterKitAlpha } from './characterKitFaceRig'

const SHAPES: Record<CharacterMouthState, string> = {
  closed: 'relaxed closed lips at rest', pressed: 'lips pressed firmly together for M, B and P',
  wide: 'an open tall mouth for A, visible dark mouth interior', medium: 'a moderately open horizontally broad mouth for E',
  small: 'a narrow horizontal mouth for I', round: 'rounded open lips for O', pucker: 'small tightly pursed round lips for U',
  bite: 'upper teeth touching the lower lip for F', tongue: 'slightly open lips with the tongue touching the upper teeth for L',
}

export function createLipsPack(name: string, takenIds: Iterable<string> = []): CharacterKit {
  return { ...createCharacterKit(name, 'cutout', takenIds), mouthMapping: {}, mouthPrompts: {},
    provenance: [{ method: 'lips-creator' }] }
}

export function lipsGenerationPrompt(pack: CharacterKit, state: CharacterMouthState, withReference = Boolean(pack.base)): string {
  const appearance = withReference
    ? 'Use the reference for the exact lip shape, color, material and drawing style.'
    : 'Create the lip shape, color, material and drawing style entirely from the description.'
  return `Create exactly ONE isolated front-facing mouth sprite: ${SHAPES[state]}. ${pack.lookNotes || 'Clean hand-drawn cartoon lips, simple shapes and clear silhouette'}. ${pack.mouthPrompts?.[state] || ''}. ${appearance} Preserve identical proportions, centered placement and lighting across all mouth states. Mouth and necessary teeth or tongue ONLY, tightly cropped, transparent background, no face, head, eyes, body, text, grid or multiple mouths.`
}

export function missingLipsSounds(pack: CharacterKit): string[] {
  return MOUTH_SOUND_GROUPS.filter(sound => pack.mouth[mouthStateForSound(sound, pack.mouthMapping)]?.reviewState !== 'approved')
}

/** Linking is explicit. Preserve the actor's identity, voice, body and existing placement. */
export function applyLipsPack(pack: CharacterKit, character: CharacterKit, poseId = 'base'): CharacterKit {
  if (missingLipsSounds(pack).length) throw new Error('Approve a mouth for every sound before linking this collection.')
  const pose = poseId === 'base' ? character.base : character.poses[poseId]
  if (!pose) throw new Error('Choose a character with a saved pose image.')
  const mouth = { ...character.mouth }
  for (const state of CHARACTER_MOUTH_STATES) {
    const asset = pack.mouth[state]
    if (!asset || asset.reviewState !== 'approved') continue
    assertFacePatchPose(asset, poseId, pose.source)
    mouth[state] = { ...asset }
  }
  const sameReference = pack.base?.source === pose.source
  return { ...character, mouth, mouthMapping: { ...pack.mouthMapping },
    ...(sameReference && pack.anchors.base ? { anchors: { ...character.anchors, [poseId]: pack.anchors.base } } : {}),
    provenance: [...character.provenance, { method: 'lips-creator-link', packId: pack.id, packUpdatedAt: pack.updatedAt }],
    updatedAt: new Date().toISOString() }
}

export function acceptLipsCandidate(pack: CharacterKit, state: CharacterMouthState, asset: CharacterKitAsset): CharacterKit {
  if (asset.alphaStatus !== 'transparent' && !asset.facePatch) throw new Error('Remove the background before accepting this mouth.')
  const candidates = { ...pack.mouthCandidates }; delete candidates[state]
  return { ...pack, mouth: { ...pack.mouth, [state]: { ...asset, reviewState: 'approved' } },
    ...(pack.mouthCandidates ? { mouthCandidates: candidates } : {}),
    provenance: [...pack.provenance, { method: 'lips-creator-accept', state, source: asset.source, previousSource: pack.mouth[state]?.source }],
    updatedAt: new Date().toISOString() }
}

export async function inspectLipsAlpha(source: string): Promise<CharacterKitAsset['alphaStatus']> {
  const response = await fetch(source)
  if (!response.ok) throw new Error('The mouth image could not be loaded.')
  const bitmap = await createImageBitmap(await response.blob())
  try {
    const canvas = document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) throw new Error('Canvas is unavailable.')
    context.drawImage(bitmap, 0, 0)
    return classifyCharacterKitAlpha(context.getImageData(0, 0, bitmap.width, bitmap.height).data).status
  } finally { bitmap.close() }
}
