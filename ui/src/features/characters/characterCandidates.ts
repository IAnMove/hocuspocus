import { checkRigPose, keyStudioImage, type RigCheck } from '../../api/characters'
import { generateImageAsset } from '../../lib/imageGeneration'
import { characterStylePrompt, type CharacterStyle, type CharacterStyleKind, type ChromaScreen } from '../../lib/characterStyles'

/** How many options a request makes unless it says otherwise; one to this many can be asked for. */
export const CANDIDATE_COUNT = 3
/** Full-body portrait size used for the Uncanny Valley cast. */
export const CANDIDATE_RESOLUTION = '896x1152'

export const candidateCount = (count: number | undefined) => Math.min(CANDIDATE_COUNT, Math.max(1, Math.round(count ?? CANDIDATE_COUNT)))

/** generating → drawn (the picture is there, its background still on, and it can already be picked) → keying → ready. */
export type KeyedCandidate = {
  id: string
  seed: number
  status: 'generating' | 'drawn' | 'keying' | 'ready' | 'failed'
  /** The image job that draws it: kept so a reloaded page can follow it again instead of starting over. */
  jobId?: string
  /** The screen colour it was drawn on, which is the one to key out. */
  screen?: ChromaScreen
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

export type CandidateRequest = {
  workspace: string; style: CharacterStyle; kind: CharacterStyleKind; description: string; model: string
  references?: string[]; signal: AbortSignal
  onUpdate: (candidates: KeyedCandidate[]) => void; onJobSubmitted?: (jobId: string) => void
  /** How many to make (1 to 3). */
  count?: number
  /** Options from an earlier run (a reloaded page): the ones still drawing are followed, the others kept. */
  existing?: KeyedCandidate[]
  /** The option the person picked, read before each background is removed. */
  picked?: () => string | undefined
}

/**
 * The options of one description on a plain screen. All the pictures are drawn first, so nothing else competes with the
 * image model for the GPU; then the backgrounds are removed one at a time. As soon as one option is picked it is the only
 * one whose background is removed: the others stay as drawn (and are keyed later if the person picks one of them).
 */
export async function generateKeyedCandidates(request: CandidateRequest, dependencies: Partial<CandidateDependencies> = {}): Promise<KeyedCandidate[]> {
  const deps = { ...defaults, ...dependencies }
  const { prompt, negative, screen } = characterStylePrompt(request.style, request.kind, request.description)
  let candidates: KeyedCandidate[] = request.existing?.length ? request.existing
    : Array.from({ length: candidateCount(request.count) }, (_, index) => ({ id: `candidate-${index + 1}`, seed: deps.seed(), status: 'generating' as const, screen }))
  const update = (id: string, patch: Partial<KeyedCandidate>) => {
    candidates = candidates.map(candidate => candidate.id === id ? { ...candidate, ...patch } : candidate)
    request.onUpdate(candidates)
  }
  request.onUpdate(candidates)
  await Promise.all(candidates.filter(candidate => candidate.status === 'generating').map(async candidate => {
    try {
      const image = await deps.generate('maestro', prompt, request.model, undefined, negative, {
        workspace: request.workspace, signal: request.signal, cleanModelDefaults: true, comicPanel: false,
        resolution: CANDIDATE_RESOLUTION, aspectRatio: '3:4', seed: candidate.seed,
        ...(request.references?.length ? { references: request.references, referenceMode: 'identity' as const } : {}),
        ...(candidate.jobId ? { existingJobId: candidate.jobId } : {}),
        onJobSubmitted: id => { update(candidate.id, { jobId: id }); request.onJobSubmitted?.(id) },
      })
      request.signal.throwIfAborted()
      update(candidate.id, { status: 'drawn', raw: image.source })
    } catch (error) {
      if (request.signal.aborted) return
      update(candidate.id, { status: 'failed', error: (error as Error).message })
    }
  }))
  for (;;) {
    request.signal.throwIfAborted()
    const chosen = request.picked?.()
    const next = candidates.find(candidate => candidate.status === 'drawn' && (!chosen || candidate.id === chosen))
    if (!next) break
    await keyCandidate({ workspace: request.workspace, candidate: next, signal: request.signal, onUpdate: patch => update(next.id, patch) }, deps)
  }
  request.signal.throwIfAborted()
  return candidates
}

/** Removes the background of one drawn option and checks it for the rig. A failure stays on that option. */
export async function keyCandidate(request: {
  workspace: string; candidate: KeyedCandidate; signal: AbortSignal; onUpdate: (patch: Partial<KeyedCandidate>) => void
}, dependencies: Partial<CandidateDependencies> = {}): Promise<void> {
  const deps = { ...defaults, ...dependencies }
  const { candidate, signal } = request
  if (!candidate.raw) return
  request.onUpdate({ status: 'keying' })
  try {
    const keyed = await deps.key({ workspace: request.workspace, source: candidate.raw, mode: candidate.screen ?? 'green',
      intentId: `character-key-${candidate.seed}` })
    signal.throwIfAborted()
    const rig = await readRigCheck(deps.check, request.workspace, keyed.url, signal)
    request.onUpdate({ status: 'ready', keyed: keyed.url, ...(keyed.report?.haze ? { haze: keyed.report.semiTransparentShare } : {}),
      ...(rig ? { rig } : {}) })
  } catch (error) {
    if (signal.aborted) return
    request.onUpdate({ status: 'failed', error: (error as Error).message })
  }
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
