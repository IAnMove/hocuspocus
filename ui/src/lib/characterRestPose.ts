import type { CharacterKit, CharacterKitAsset } from './characterKit'
import { isFacePatchCompatible } from './characterFacePatch'

export function characterRestPoseKey(kit: CharacterKit): string | undefined {
  const base = kit.base, mouth = kit.mouth.closed, anchors = kit.anchors.base
  if (!base?.source || !mouth?.source || !anchors || base.reviewState === 'rejected' || mouth.reviewState === 'rejected'
    || !isFacePatchCompatible(mouth, 'base', base.source)) return undefined
  return JSON.stringify([1, base.id, base.source, base.reviewState, mouth.id, mouth.source, mouth.reviewState,
    mouth.facePatch, anchors.mouthStates?.closed ?? anchors.mouth])
}

export function characterRestPoseSource(kit: CharacterKit): string | undefined {
  return kit.restPose?.fingerprint === characterRestPoseKey(kit) ? kit.restPose?.asset.source : undefined
}

/** The rig keeps a mouthless base; still references get the composed resting face. */
export async function prepareCharacterRestPose(kit: CharacterKit, workspace: string,
  upload: (file: File) => Promise<{ url?: string; filename?: string }>,
  fileUrl: (filename: string, workspace: string) => string): Promise<CharacterKit> {
  const fingerprint = characterRestPoseKey(kit)
  if (!fingerprint) return kit.restPose ? { ...kit, restPose: undefined } : kit
  if (characterRestPoseSource(kit)) return kit
  const read = async (asset: CharacterKitAsset) => {
    const url = /^(https?:|\/)/.test(asset.source) ? asset.source : fileUrl(asset.source, workspace)
    const response = await fetch(url)
    if (!response.ok) throw new Error('The saved resting face could not load its source image.')
    return createImageBitmap(await response.blob())
  }
  const base = await read(kit.base!)
  try {
    const mouth = await read(kit.mouth.closed!)
    try {
      const blob = await composeCharacterRestPose(base, mouth, kit)
      const result = await upload(new File([blob], `${kit.id}-rest.png`, { type: 'image/png' }))
      const source = result.url || (result.filename ? `/api/v1/uploads/${encodeURIComponent(result.filename)}` : '')
      if (!source) throw new Error('The resting face was not saved.')
      return { ...kit, restPose: { fingerprint, asset: { ...kit.base!, id: `${kit.id.slice(0, 100)}-rest`,
        name: `${kit.name.slice(0, 230)} · rest`, source, workspace,
        reviewState: kit.base!.reviewState === 'approved' && kit.mouth.closed!.reviewState === 'approved' ? 'approved' : 'pending' } } }
    } finally { mouth.close() }
  } finally { base.close() }
}

export async function composeCharacterRestPose(base: ImageBitmap, mouth: ImageBitmap, kit: CharacterKit): Promise<Blob> {
  if (base.width * base.height > 16_777_216) throw new Error('Use a character image up to 16 megapixels.')
  const canvas = document.createElement('canvas')
  canvas.width = base.width; canvas.height = base.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('The resting face could not be composed.')
  context.drawImage(base, 0, 0)
  const group = kit.anchors.base!, anchor = group.mouthStates?.closed ?? group.mouth
  const edge = Math.max(base.width, base.height), size = edge * anchor.scale
  const fit = Math.min(size / mouth.width, size / mouth.height)
  context.translate(base.width / 2 + edge * anchor.offsetX / 100, base.height / 2 + edge * anchor.offsetY / 100)
  context.rotate(anchor.rotation * Math.PI / 180)
  context.drawImage(mouth, -mouth.width * fit / 2, -mouth.height * fit / 2, mouth.width * fit, mouth.height * fit)
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('The resting face could not be encoded.')), 'image/png'))
}
