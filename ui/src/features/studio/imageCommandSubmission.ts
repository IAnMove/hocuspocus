import * as api from '../../api/client'
import { BASE } from '../../api/http'
import { stableSerialize } from '../../lib/commandContract'
import type { AppState } from '../../stores/useStore'
import type { GenerationSubmissionContext } from './generationProvenance'
import type { ImageGenerationReceipt } from '../../api/imageGenerationCommands'
import { finishStudioImageCommand, presentStudioImageCommand } from './imageCommandPresentation'
import i18n from '../../i18n'

type StudioState = AppState
type NativeReceipt = Awaited<ReturnType<typeof api.submitGeneration>>
interface Submission {
  params: Record<string, unknown>
  receipt?: ImageGenerationReceipt
  submit: () => Promise<NativeReceipt>
}

const MEDIA_FIELDS = ['image_refs', 'image_start', 'image_end', 'image_guide', 'image_mask'] as const
const FORM_FIELDS = ['params', 'activeWorkspace', 'generationMode', 'imageRefs', 'imageRefType',
  'removeBackgroundRefs', 'loraWeights', 'spatialUpsampling', 'filmGrainIntensity', 'filmGrainSaturation',
  'startImage', 'endImage', 'settingsOpen', 'dashboardOpen', 'sidebarMode'] as const

function assertSameForm(before: StudioState, current: StudioState): void {
  if (FORM_FIELDS.some(field => before[field] !== current[field])) {
    throw new Error(i18n.t('studio:commands.contextChanged'))
  }
}

async function canonicalReferences(params: Record<string, unknown>): Promise<void> {
  const { materializeLocalEditImage } = await import('../../lib/localEditImages')
  for (const field of MEDIA_FIELDS) {
    const original = params[field]
    if (!original) continue
    params[field] = Array.isArray(original)
      ? await Promise.all(original.map(item => materializeLocalEditImage(item)))
      : await materializeLocalEditImage(original)
  }
  for (const field of MEDIA_FIELDS) {
    const value = params[field]
    const values = Array.isArray(value) ? value : value ? [value] : []
    if (values.some(item => typeof item === 'string' && item && !item.startsWith('/api/v1/') && !item.startsWith('asset'))) {
      throw new Error(i18n.t('studio:commands.referenceFailed'))
    }
  }
  const fields = MEDIA_FIELDS.filter(field => params[field])
  const references = fields.flatMap(field => Array.isArray(params[field]) ? params[field] as unknown[] : [params[field]])
    .filter(value => value !== '')
  if (!references.length) return
  const response = await fetch(`${BASE}/api/v1/generation/commands/references`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ references }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail?.message || i18n.t('studio:commands.referenceFailed'))
  }
  const result = await response.json() as { references?: unknown }
  if (!Array.isArray(result.references) || result.references.length !== references.length
      || result.references.some(value => typeof value !== 'string')) {
    throw new Error(i18n.t('studio:commands.referenceFailed'))
  }
  const resolved = result.references as string[]
  let cursor = 0
  const replace = (value: unknown) => value === '' ? '' : resolved[cursor++]
  for (const field of fields) {
    const original = params[field]
    params[field] = Array.isArray(original) ? original.map(replace) : replace(original)
  }
}

/** Bind legacy form field names without discarding conflicting image inputs. */
export function translateLegacyImageGuides(params: Record<string, unknown>): void {
  for (const [legacy, canonical] of [['video_guide', 'image_guide'], ['video_mask', 'image_mask']]) {
    const value = params[legacy]
    if (!value) continue
    if (params[canonical] && stableSerialize(params[canonical]) !== stableSerialize(value)) {
      throw new Error(i18n.t('studio:commands.conflictingGuides'))
    }
    params[canonical] = value
    delete params[legacy]
  }
}

/** Called after the complete native form builder; never reduces its parameters. */
export async function prepareStudioSubmission(
  params: Record<string, unknown>, before: StudioState, current: () => StudioState,
  context?: GenerationSubmissionContext, referenceErrors: string[] = [],
): Promise<Submission> {
  if (before.generationMode !== 'image') return { params, submit: () => api.submitGeneration(params) }
  let snapshot = params
  try {
    const { newImageGenerationIntentId, submitImageGenerationCommand, createStudioImageGenerationCommand } =
      await import('../../api/imageGenerationCommands')
    if (referenceErrors.length) throw new Error(i18n.t('studio:commands.referenceFailed'))
    snapshot = JSON.parse(stableSerialize(params)) as Record<string, unknown>
    translateLegacyImageGuides(snapshot)
    assertSameForm(before, current())
    await canonicalReferences(snapshot)
    assertSameForm(before, current())
    const command = createStudioImageGenerationCommand(snapshot, context?.commandId || newImageGenerationIntentId())
    const submission: Submission = {
      params: { ...command.input.params, workspace: command.input.workspace },
      submit: async () => {
        try {
          const receipt = await submitImageGenerationCommand(command, {
            submissionContext: context,
            onSnapshotReady: async frozen => {
              assertSameForm(before, current())
              await presentStudioImageCommand(frozen)
              assertSameForm(before, current())
            },
          })
          submission.receipt = receipt
          finishStudioImageCommand(command.intent_id, receipt)
          return { ...receipt.result, status: receipt.status }
        } catch (error) {
          finishStudioImageCommand(command.intent_id, undefined, error instanceof Error ? error.message : String(error))
          throw error
        }
      },
    }
    return submission
  } catch (error) {
    // Let the existing submission error tile report preparation failures too.
    return { params: snapshot, submit: () => Promise.reject(error) }
  }
}
