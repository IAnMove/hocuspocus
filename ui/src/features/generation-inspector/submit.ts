import { BASE } from '../../api/http'
import { createVideoGenerationCommand, submitVideoGenerationCommand } from '../../api/videoGenerationCommands'
import { createStudioImageGenerationCommand, submitImageGenerationCommand } from '../../api/imageGenerationCommands'
import { REF_ROLES } from './refs'
import type { ClonePlan, PortableRecipe } from './types'

function parameters(plan: ClonePlan): Record<string, unknown> {
  const params = { ...plan.params, prompt: plan.prompt, negative_prompt: plan.negativePrompt,
    model_type: plan.model.id.known ? plan.model.id.value : '', workspace: plan.outputFolder }
  const result: Record<string, unknown> = params
  for (const role of REF_ROLES) {
    const refs = plan.refs.filter(ref => ref.role === role)
    if (!refs.length) continue
    const urls = refs.map(ref => {
      if (ref.missing) throw new Error(`Missing reference: ${role}`)
      if (ref.uri) return ref.uri
      if (!ref.filename) throw new Error(`Unresolved reference: ${role}`)
      return `/api/v1/file/${encodeURIComponent(ref.filename)}?workspace=${encodeURIComponent(ref.workspace || plan.outputFolder)}`
    })
    result[role] = Array.isArray(plan.params[role]) || role.endsWith('_refs') ? urls : urls[0]
  }
  return result
}

async function recoverReceipt(plan: ClonePlan): Promise<string> {
  if (!plan.intentKnown || !plan.intentId) throw new Error('This attempt has no stored command identity')
  // Metadata is a projection, not the original immutable command. Never rebuild
  // a transport retry from redacted params or a transformed prompt.
  const query = new URLSearchParams({ workspace: plan.outputFolder, intent_id: plan.intentId })
  const response = await fetch(`${BASE}/api/v1/generation/commands/receipt?${query}`)
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail?.message || 'No admitted command found; clone to create a new attempt')
  if (body.receipt?.commandId !== plan.intentId || body.receipt?.result?.workspace !== plan.outputFolder) {
    throw new Error('Receipt does not match this attempt')
  }
  return body.receipt.result.task_id
}

export async function submitInspectorPlan(plan: ClonePlan, recipe: PortableRecipe): Promise<string> {
  if (plan.kind === 'retry') return recoverReceipt(plan)
  const params = parameters(plan)
  const options = { submissionContext: { actor: 'user' as const, commandId: plan.intentId, runId: plan.generationId } }
  const mode = params.generation_mode || (params.image_mode === 1 ? 'image' : recipe.mode)
  if (mode === 'image') {
    return (await submitImageGenerationCommand(createStudioImageGenerationCommand(params, plan.intentId), options)).result.task_id
  }
  if (mode === 'video') {
    return (await submitVideoGenerationCommand(createVideoGenerationCommand(params, plan.intentId), options)).result.task_id
  }
  const submode = params.audio_sub_mode || params.audio_submode || recipe.mode
  if (submode === 'speech') {
    const api = await import('../../api/speechGenerationCommands')
    return (await api.submitSpeechGenerationCommand(api.createSpeechGenerationCommand(params, plan.intentId), options)).result.task_id
  }
  if (submode === 'music') {
    const api = await import('../../api/musicGenerationCommands')
    return (await api.submitMusicGenerationCommand(api.createMusicGenerationCommand(params, plan.intentId), options)).result.task_id
  }
  if (submode === 'sfx') {
    const api = await import('../../api/sfxGenerationCommands')
    return (await api.submitSfxGenerationCommand(api.createSfxGenerationCommand(params, plan.intentId), options)).result.task_id
  }
  throw new Error('This generation mode cannot be cloned here. Open its recipe in Studio.')
}
