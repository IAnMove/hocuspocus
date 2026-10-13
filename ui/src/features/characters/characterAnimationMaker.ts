import { buildAnimationSheet, fetchAnimationPrompt, keyStudioImage } from '../../api/characters'
import { generateImageAsset } from '../../lib/imageGeneration'
import { animationDescription, animationReference, kitStyleId, type AnimationDef, type KitAnimation } from '../../lib/characterAnimations'
import type { CharacterKit } from '../../lib/characterKit'

export type PoseTake = {
  id: string
  /** `reused`: kept from an earlier run, so one pose can be made again without the others. */
  status: 'waiting' | 'reused' | 'generating' | 'keying' | 'ready' | 'failed'
  seed: number
  raw?: string
  keyed?: string
  error?: string
}
export type MakeStage = 'poses' | 'sheet'
export type MadeAnimation = Omit<KitAnimation, 'reviewState'>

export type MakerDependencies = {
  generate: typeof generateImageAsset
  key: typeof keyStudioImage
  prompt: typeof fetchAnimationPrompt
  sheet: typeof buildAnimationSheet
  seed: () => number
}

const defaults: MakerDependencies = {
  generate: generateImageAsset, key: keyStudioImage, prompt: fetchAnimationPrompt, sheet: buildAnimationSheet,
  seed: () => Math.floor(Math.random() * 2_000_000_000),
}

type Aspect = '1:1' | '3:4' | '4:3' | '2:3' | '3:2' | '9:16' | '16:9'
const ASPECTS: Array<[Aspect, number]> = [['1:1', 1], ['3:4', 3 / 4], ['4:3', 4 / 3], ['2:3', 2 / 3], ['3:2', 3 / 2], ['9:16', 9 / 16], ['16:9', 16 / 9]]

/** The nearest named aspect of a `WxH` resolution: the model is given the exact size, the aspect only labels the request. */
export function aspectOf(resolution: string): Aspect {
  const [width, height] = resolution.split('x').map(Number)
  if (!width || !height) return '1:1'
  const ratio = width / height
  return ASPECTS.reduce((best, item) => Math.abs(item[1] - ratio) < Math.abs(best[1] - ratio) ? item : best)[0]
}

/** Every pose of an animation, one after another (one GPU): the character's own picture is each one's identity reference,
 * each is keyed on its screen as soon as it arrives, and the keyed poses are joined into one sheet. `reuse` names poses
 * (id → keyed picture) to keep as they are. A failed pose stops the run and leaves the others in `onUpdate`. */
export async function makeAnimation(request: {
  workspace: string; kit: CharacterKit; def: AnimationDef; model: string; signal: AbortSignal
  reuse?: Record<string, string>
  onUpdate: (takes: PoseTake[], stage: MakeStage) => void; onJobSubmitted?: (jobId: string) => void
}, dependencies: Partial<MakerDependencies> = {}): Promise<MadeAnimation> {
  const deps = { ...defaults, ...dependencies }
  const reference = animationReference(request.kit)
  if (!reference) throw new Error(`Character Kit “${request.kit.name}” has no persistent picture to make poses from.`)
  const description = animationDescription(request.kit)
  const style = kitStyleId(request.kit)
  let takes: PoseTake[] = request.def.poses.map(pose => {
    const kept = request.reuse?.[pose.id]
    return kept ? { id: pose.id, status: 'reused', seed: 0, keyed: kept } : { id: pose.id, status: 'waiting', seed: deps.seed() }
  })
  const update = (id: string, patch: Partial<PoseTake>, stage: MakeStage = 'poses') => {
    takes = takes.map(take => take.id === id ? { ...take, ...patch } : take)
    request.onUpdate(takes, stage)
  }
  request.onUpdate(takes, 'poses')
  let firstPrompt = ''
  for (const take of takes) {
    if (take.status === 'reused') continue
    request.signal.throwIfAborted()
    try {
      update(take.id, { status: 'generating' })
      const words = request.def.poses.find(pose => pose.id === take.id)?.prompt ?? ''
      const asked = await deps.prompt({ animation: request.def.id, pose: take.id, description, ...(style ? { style } : {}),
        ...(request.def.custom ? { custom: { view: request.def.view, text: words } } : {}), signal: request.signal })
      firstPrompt ||= asked.prompt
      const image = await deps.generate('maestro', asked.prompt, request.model, undefined, asked.negative, {
        workspace: request.workspace, signal: request.signal, cleanModelDefaults: true, comicPanel: false,
        resolution: asked.resolution, aspectRatio: aspectOf(asked.resolution), seed: take.seed,
        references: [reference], referenceMode: 'identity' as const, strictReference: true, onJobSubmitted: request.onJobSubmitted,
      })
      request.signal.throwIfAborted()
      update(take.id, { status: 'keying', raw: image.source })
      const keyed = await deps.key({ workspace: request.workspace, source: image.source, mode: asked.screen,
        intentId: `animation-key-${request.kit.id}-${request.def.id}-${take.id}-${take.seed}` })
      request.signal.throwIfAborted()
      update(take.id, { status: 'ready', keyed: keyed.url })
    } catch (error) {
      if (request.signal.aborted) throw error
      update(take.id, { status: 'failed', error: (error as Error).message })
      throw error
    }
  }
  request.onUpdate(takes, 'sheet')
  const sources = takes.map(take => take.keyed!)
  const sheet = await deps.sheet({ workspace: request.workspace, sources, name: `${request.kit.id}-${request.def.id}`, scaleBy: request.def.scaleBy, signal: request.signal })
  return {
    sheet: { source: sheet.source, width: sheet.width, height: sheet.height, count: sheet.count, columns: sheet.columns, rows: sheet.rows, cell: sheet.cell },
    // What the author wrote for a pose stays with it, so that pose can be made again alone.
    frames: takes.map(take => ({ id: take.id, source: take.keyed!, ...(request.def.custom ? frameWords(request.def, take.id) : {}) })),
    fps: request.def.fps, loop: request.def.loop, facing: request.def.facing, view: request.def.view, scaleBy: request.def.scaleBy, model: request.model,
    ...(request.def.custom ? { title: request.def.title.es } : {}),
    ...(firstPrompt ? { prompt: firstPrompt } : {}),
  }
}

function frameWords(def: AnimationDef, id: string): { prompt?: string; label?: string } {
  const pose = def.poses.find(item => item.id === id)
  return pose ? { prompt: pose.prompt, label: pose.label.es } : {}
}

/** What a retry can keep: the poses of a failed or partial run that were made and keyed. */
export function keptPoses(takes: PoseTake[]): Record<string, string> {
  return Object.fromEntries(takes.filter(take => (take.status === 'ready' || take.status === 'reused') && take.keyed).map(take => [take.id, take.keyed!]))
}
