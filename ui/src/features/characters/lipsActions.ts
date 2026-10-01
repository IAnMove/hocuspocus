import { fetchLipsLibrary, runLipsCommand } from '../../api/lipsCreator'
import { generateLipsMouth } from '../../lib/lipsGeneration'
import { CHARACTER_MOUTH_STATES, type CharacterMouthState } from '../../lib/characterMouthStates'
import { characterImageModels, preferredCharacterImageModel } from '../../lib/characterImageModels'
import { useStore } from '../../stores/useStore'
import type { GenerationSubmissionContext } from '../studio/generationProvenance'
import type { LipsCollectionCommand, GenerateLipsCommand } from './lipsCommands'

function summaries(result: Awaited<ReturnType<typeof runLipsCommand>>) {
  return { ...result, ...(result.library ? { library: { revision: result.library.revision, packs: Object.values(result.library.kits).map(pack => ({
    id: pack.id, name: pack.name, mouthMapping: pack.mouthMapping, mouths: Object.fromEntries(Object.entries(pack.mouth).map(([state, asset]) => [state, asset?.reviewState])),
    candidates: Object.keys(pack.mouthCandidates || {}),
  })) } } : {}) }
}

export async function manageLipsCollection(action: LipsCollectionCommand, workspace: string) {
  const operation = `lips.${action.operation}`
  const mutation = !['list', 'generation.plan'].includes(action.operation)
  const result = await runLipsCommand(workspace, operation, action.input, mutation ? `wizard-lips-${crypto.randomUUID()}` : undefined)
  const kit = result.library?.kits[result.character_id || result.pack_id || '']
  return { message: `${operation}: completed.`, metadata: summaries(result), target: {
    kind: result.character_id ? 'character_kit' : 'lips_creator', id: result.character_id || result.pack_id || workspace, title: kit?.name || 'Lips Creator',
  } }
}

function collectionUsesReference(pack: { mouthGenerationMode?: string; base?: unknown }) {
  if (pack.mouthGenerationMode) return pack.mouthGenerationMode === 'reference'
  return Boolean(pack.base)
}

function installedLipsModel(action: GenerateLipsCommand, withReference: boolean) {
  const models = characterImageModels(useStore.getState().models, withReference)
  const model = action.model || preferredCharacterImageModel(models, withReference)
  if (!model || !models.some(item => item.model_type === model)) {
    throw new Error('Choose an installed image model compatible with the collection.')
  }
  return model
}

function statesToGenerate(pack: Awaited<ReturnType<typeof fetchLipsLibrary>>['kits'][string], requested?: CharacterMouthState[]): CharacterMouthState[] {
  if (requested) return requested
  return CHARACTER_MOUTH_STATES.filter(state => !pack.mouthCandidates?.[state] && mouthNeedsGeneration(pack.mouth[state]))
}

function mouthNeedsGeneration(asset: { reviewState?: string } | undefined) {
  return !asset || asset.reviewState === 'rejected'
}

async function captureGeneratedState(pack: Awaited<ReturnType<typeof fetchLipsLibrary>>['kits'][string], state: CharacterMouthState, model: string, workspace: string, revision: number, context: { generationContext?: GenerationSubmissionContext }) {
  let terminalFailure = false
  let generated: Awaited<ReturnType<typeof generateLipsMouth>>
  try {
    generated = await generateLipsMouth(pack, state, model, workspace, { submissionContext: context.generationContext,
      onStatus(status) { terminalFailure = status.status === 'failed' || status.status === 'cancelled' } })
  } catch (cause) {
    if (!terminalFailure) throw cause
    return { failure: (cause as Error).message, library: undefined }
  }
  const saved = await runLipsCommand(workspace, 'lips.capture', { pack_id: pack.id, base_revision: revision, state, asset: generated.asset }, `wizard-lips-${crypto.randomUUID()}`)
  if (!saved.library) throw new Error('The generated mouth could not be saved. Generation stopped.')
  return { failure: '', library: saved.library }
}

export async function generateLipsCollection(action: GenerateLipsCommand, workspace: string, context: { onStep?: (message: string) => void; generationContext?: GenerationSubmissionContext } = {}) {
  let library = await fetchLipsLibrary(workspace)
  const pack = library.kits[action.packId]
  if (!pack) throw new Error('Mouth collection not found. List collections and use an exact pack ID.')
  const withReference = collectionUsesReference(pack)
  if (withReference && !pack.base) throw new Error('Choose a reference or description mode before generating.')
  const model = installedLipsModel(action, withReference)
  const states = statesToGenerate(pack, action.states)
  const failures: Record<string, string> = {}
  let completed = 0
  for (const [index, state] of states.entries()) {
    context.onStep?.(`Lips Creator: ${state} (${index + 1}/${states.length})…`)
    const saved = await captureGeneratedState(pack, state, model, workspace, library.revision, context)
    if (saved.failure) failures[state] = saved.failure
    if (!saved.library) continue
    library = saved.library
    completed += 1
  }
  return lipsGenerationReport(pack, completed, states.length, failures, library.revision)
}

function lipsGenerationReport(pack: { id: string; name: string }, completed: number, total: number, failures: Record<string, string>, revision: number) {
  const body = { message: `Lips Creator: ${completed}/${total} mouths generated and saved for review.`,
    metadata: { pack_id: pack.id, completed, total, failures, revision, reviewRequired: true },
    target: { kind: 'lips_creator' as const, id: pack.id, title: pack.name } }
  if (!Object.keys(failures).length) return body
  return { ...body, report: { state: 'partial' as const, message: `${completed}/${total} mouths saved.`, metadata: { failures }, recoverable: true } }
}
