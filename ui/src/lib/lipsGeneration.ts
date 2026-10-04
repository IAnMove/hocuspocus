import { generateImageAsset, type LocalImageOptions } from './imageGeneration'
import type { CharacterKit, CharacterKitAsset, CharacterMouthState } from './characterKit'
import { inspectLipsAlpha, lipsGenerationPrompt } from './lipsCreator'

/** Both Lips Creator and the Wizard submit through the same native image path. */
export async function generateLipsMouth(pack: CharacterKit, state: CharacterMouthState, model: string, workspace: string,
  options: Pick<LocalImageOptions, 'signal' | 'onStatus' | 'onJobSubmitted' | 'submissionContext'> = {}) {
  const withReference = pack.mouthGenerationMode ? pack.mouthGenerationMode === 'reference' : Boolean(pack.base)
  const reference = withReference ? pack.base?.source : undefined
  if (withReference && !reference) throw new Error('Choose a reference or use description mode.')
  const prompt = lipsGenerationPrompt(pack, state, Boolean(reference))
  if (prompt.length > 4000) throw new Error('Shorten the collection description or per-mouth prompt before generating.')
  const result = await generateImageAsset('maestro', prompt, model, reference,
    'face, head, eyes, body, multiple mouths, sprite sheet, text, watermark, checkerboard, background, skin rectangle',
    { ...options, workspace, cleanModelDefaults: true, strictReference: Boolean(reference), referenceMode: 'identity', resolution: '1024x1024', aspectRatio: '1:1' })
  options.signal?.throwIfAborted()
  const alphaStatus = await inspectLipsAlpha(result.source).catch(() => 'unknown' as const)
  options.signal?.throwIfAborted()
  const asset: CharacterKitAsset = { id: `mouth-${state}-${Date.now().toString(36)}`, name: `${pack.name} · ${state}`, source: result.source,
    kind: 'overlay', alphaStatus, reviewState: 'pending', model: result.model || model, prompt, workspace }
  return { asset, jobId: result.metadata?.jobId }
}
