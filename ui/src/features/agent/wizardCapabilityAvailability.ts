import { getCapability, listCapabilities, type CapabilityDefinition } from './capabilityRegistry'

export type WizardCapabilityAvailabilityStatus =
  | 'executable'
  | 'needs_data'
  | 'blocked'
  | 'requires_navigation'

export interface WizardCapabilityAvailability {
  name: string
  status: WizardCapabilityAvailabilityStatus
  reason: string
}

export interface WizardAvailabilityLabs {
  story: { project_id: string; active_cue_title?: string; selected_song_id?: string }
  series: { series_id: string; episode_id: string; shots: number; approved: number }
}

export interface WizardAvailabilityContext {
  location: { tab: string }
  labs: WizardAvailabilityLabs
  pendingQuestion?: unknown
}

export interface WizardContextCapabilityProjection {
  available: string[]
  blocked: Array<{ name: string; reason: string }>
  statuses: WizardCapabilityAvailability[]
}

const STORY_NEEDS_PROJECT = new Set([
  'update_story',
  'generate_story_section',
  'apply_story_proposal',
  'approve_story_section',
  'approve_story_visuals',
  'generate_story_visuals',
  'stage_story_comic',
  'stage_story_video',
  'configure_story_song',
  'generate_story_song',
  'stage_story_music_video',
  'start_director_production',
])

const SERIES_NEEDS_EPISODE = new Set([
  'update_series_episode',
  'generate_series_plan',
  'apply_series_plan',
  'render_series_shots',
  'edit_series_shot',
  'rerender_series_shot',
  'regenerate_series_line_voice',
  'review_series_attempts',
  'assemble_series_episode',
  'commit_series_canon',
  'stage_series_comic',
])

function uniqueNames(names: string[]): string[] {
  return [...new Set(names)]
}

function pendingBlocksCompute(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const record = value as { id?: unknown }
  return typeof record.id === 'string' ? Boolean(record.id.trim()) : true
}

function missingDataReason(name: string, context: WizardAvailabilityContext): string {
  const story = context.labs.story
  const series = context.labs.series
  if (STORY_NEEDS_PROJECT.has(name) && !story.project_id) {
    return 'No hay un proyecto de Story Lab abierto; créalo o nómbralo antes de esta acción.'
  }
  if (SERIES_NEEDS_EPISODE.has(name) && !series.episode_id) {
    return series.series_id
      ? 'No hay un episodio abierto; nombra el episodio exacto o créalo con create_series_episode.'
      : 'No hay una serie abierta. create_series_episode con create_if_missing=true puede crearla.'
  }
  return ''
}

function classifyCapability(
  definition: CapabilityDefinition,
  context: WizardAvailabilityContext,
): WizardCapabilityAvailability {
  const name = definition.name
  if (pendingBlocksCompute(context.pendingQuestion) && (definition.risk === 'compute' || definition.risk === 'external_cost')) {
    return {
      name,
      status: 'blocked',
      reason: 'Hay una decisión pendiente del Wizard; no lanzo generación hasta resolverla.',
    }
  }
  const missing = missingDataReason(name, context)
  if (missing) return { name, status: 'needs_data', reason: missing }
  const destination = definition.presentation.destination
  if (destination !== 'action' && destination !== context.location.tab) {
    return {
      name,
      status: 'requires_navigation',
      reason: `Puedo prepararlo abriendo ${destination}.`,
    }
  }
  return { name, status: 'executable', reason: 'Lista para ejecutar en el contexto actual.' }
}

export function deriveWizardCapabilityAvailability(
  context: WizardAvailabilityContext,
): WizardCapabilityAvailability[] {
  return listCapabilities().map(definition => classifyCapability(definition, context))
}

export function toWizardContextCapabilities(
  entries: WizardCapabilityAvailability[],
): WizardContextCapabilityProjection {
  return {
    available: uniqueNames(entries
      .filter(entry => entry.status === 'executable' || entry.status === 'requires_navigation')
      .map(entry => entry.name)),
    blocked: entries
      .filter(entry => entry.status === 'blocked' || entry.status === 'needs_data')
      .map(entry => ({ name: entry.name, reason: entry.reason })),
    statuses: entries,
  }
}

export function projectWizardContextCapabilities(
  context: WizardAvailabilityContext,
): WizardContextCapabilityProjection {
  return toWizardContextCapabilities(deriveWizardCapabilityAvailability(context))
}

export function revalidateWizardCapability(
  actionType: string,
  context: WizardAvailabilityContext,
): WizardCapabilityAvailability {
  const definition = getCapability(actionType)
  if (!definition) {
    return { name: actionType, status: 'blocked', reason: `${actionType} no está registrada.` }
  }
  return classifyCapability(definition, context)
}

export function wizardCapabilityExecutionError(
  verdict: WizardCapabilityAvailability,
): string | null {
  if (verdict.status === 'blocked' || verdict.status === 'needs_data') return verdict.reason
  return null
}
