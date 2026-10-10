import { checkRigPose, keyStudioImage, type RigCheck } from '../../api/characters'
import { generateImageAsset } from '../../lib/imageGeneration'
import { characterStylePrompt, type CharacterStyle, type CharacterStyleKind } from '../../lib/characterStyles'

export const CANDIDATE_COUNT = 3
/** Full-body portrait size used for the Uncanny Valley cast. */
export const CANDIDATE_RESOLUTION = '896x1152'

export type KeyedCandidate = {
  id: string
  seed: number
  status: 'generating' | 'keying' | 'ready' | 'failed'
  raw?: string
  keyed?: string
  error?: string
  /** Share of the keyed image still semi-transparent when studio.key reports a haze (the screen did not key cleanly). */
  haze?: number
  /** characters.rig.check on the keyed pose. Absent when the check did not answer. */
  rig?: { ready: boolean; reasons: string[] }
}

export type CandidateDependencies = {
  generate: typeof generateImageAsset
  key: typeof keyStudioImage
  seed: () => number
  check: typeof checkRigPose
}

const defaults: CandidateDependencies = {
  generate: generateImageAsset, key: keyStudioImage, seed: () => Math.floor(Math.random() * 2_000_000_000),
  check: checkRigPose,
}

/** Three takes of one description on a plain screen; each is keyed as soon as it arrives. */
export async function generateKeyedCandidates(request: {
  workspace: string; style: CharacterStyle; kind: CharacterStyleKind; description: string; model: string
  references?: string[]; signal: AbortSignal
  onUpdate: (candidates: KeyedCandidate[]) => void; onJobSubmitted?: (jobId: string) => void
}, dependencies: Partial<CandidateDependencies> = {}): Promise<KeyedCandidate[]> {
  const deps = { ...defaults, ...dependencies }
  const { prompt, negative, screen } = characterStylePrompt(request.style, request.kind, request.description)
  let candidates: KeyedCandidate[] = Array.from({ length: CANDIDATE_COUNT },
    (_, index) => ({ id: `candidate-${index + 1}`, seed: deps.seed(), status: 'generating' }))
  const update = (id: string, patch: Partial<KeyedCandidate>) => {
    candidates = candidates.map(candidate => candidate.id === id ? { ...candidate, ...patch } : candidate)
    request.onUpdate(candidates)
  }
  request.onUpdate(candidates)
  await Promise.all(candidates.map(async candidate => {
    try {
      const image = await deps.generate('maestro', prompt, request.model, undefined, negative, {
        workspace: request.workspace, signal: request.signal, cleanModelDefaults: true, comicPanel: false,
        resolution: CANDIDATE_RESOLUTION, aspectRatio: '3:4', seed: candidate.seed,
        ...(request.references?.length ? { references: request.references, referenceMode: 'identity' as const } : {}),
        onJobSubmitted: request.onJobSubmitted,
      })
      request.signal.throwIfAborted()
      update(candidate.id, { status: 'keying', raw: image.source })
      const keyed = await deps.key({ workspace: request.workspace, source: image.source, mode: screen,
        intentId: `character-key-${candidate.seed}` })
      request.signal.throwIfAborted()
      const rig = await readRigCheck(deps.check, request.workspace, keyed.url, request.signal)
      update(candidate.id, { status: 'ready', keyed: keyed.url, ...(keyed.report?.haze ? { haze: keyed.report.semiTransparentShare } : {}),
        ...(rig ? { rig } : {}) })
    } catch (error) {
      if (request.signal.aborted) return
      update(candidate.id, { status: 'failed', error: (error as Error).message })
    }
  }))
  request.signal.throwIfAborted()
  return candidates
}

/** The check is optional in the sense that a failure, or a body with no boolean `ready`, leaves the candidate usable. */
async function readRigCheck(check: typeof checkRigPose, workspace: string, source: string, signal: AbortSignal): Promise<KeyedCandidate['rig']> {
  try {
    const checked: RigCheck = await check({ workspace, source, signal })
    if (typeof checked?.ready !== 'boolean') return undefined
    const reasons = Array.isArray(checked.reasons) ? checked.reasons.filter(reason => typeof reason === 'string') : []
    return { ready: checked.ready, reasons }
  } catch (error) {
    if (signal.aborted) throw error
    return undefined
  }
}
