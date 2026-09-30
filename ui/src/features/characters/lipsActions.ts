import { fetchLipsLibrary, runLipsCommand } from '../../api/lipsCreator'
import { generateLipsMouth } from '../../lib/lipsGeneration'
import { CHARACTER_MOUTH_STATES } from '../../lib/characterMouthStates'
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

export async function generateLipsCollection(action: GenerateLipsCommand, workspace: string, context: { onStep?: (message: string) => void; generationContext?: GenerationSubmissionContext } = {}) {
  const ws = workspace
  let library = await fetchLipsLibrary(ws)
  const pack = library.kits[action.packId]
  if (!pack) throw new Error('Mouth collection not found. List collections and use an exact pack ID.')
  const withReference = pack.mouthGenerationMode ? pack.mouthGenerationMode === 'reference' : Boolean(pack.base)
  if (withReference && !pack.base) throw new Error('Choose a reference or description mode before generating.')
  const models = characterImageModels(useStore.getState().models, withReference)
  const model = action.model || preferredCharacterImageModel(models, withReference)
  if (!model || !models.some(item => item.model_type === model)) throw new Error('Choose an installed image model compatible with the collection.')
  const states = action.states || CHARACTER_MOUTH_STATES.filter(state => !pack.mouthCandidates?.[state] && (!pack.mouth[state] || pack.mouth[state]?.reviewState === 'rejected'))
  const failures: Record<string, string> = {}
  let completed = 0
  for (const [index, state] of states.entries()) {
    context.onStep?.(`Lips Creator: ${state} (${index + 1}/${states.length})…`)
    let terminalFailure = false
    let generated: Awaited<ReturnType<typeof generateLipsMouth>>
    try {
      generated = await generateLipsMouth(pack, state, model, ws, { submissionContext: context.generationContext,
        onStatus(status) { terminalFailure = status.status === 'failed' || status.status === 'cancelled' } })
    } catch (cause) {
      // An uncertain status can leave a native job running. Only advance after confirmed terminal failure.
      if (!terminalFailure) throw cause
      failures[state] = (cause as Error).message
      continue
    }
    const saved = await runLipsCommand(ws, 'lips.capture', { pack_id: pack.id, base_revision: library.revision, state, asset: generated.asset }, `wizard-lips-${crypto.randomUUID()}`)
    if (!saved.library) throw new Error('The generated mouth could not be saved. Generation stopped.')
    library = saved.library
    completed += 1
  }
  return { message: `Lips Creator: ${completed}/${states.length} mouths generated and saved for review.`,
    metadata: { pack_id: pack.id, completed, total: states.length, failures, revision: library.revision, reviewRequired: true },
    target: { kind: 'lips_creator', id: pack.id, title: pack.name },
    ...(Object.keys(failures).length ? { report: { state: 'partial' as const, message: `${completed}/${states.length} mouths saved.`, metadata: { failures }, recoverable: true } } : {}),
  }
}
