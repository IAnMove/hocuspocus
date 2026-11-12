import type { ActivityGroup, ActivityTaskLike } from './lineage'
import { generationInitiator } from './taskPresentation'

type Translate = (key: string, options?: object) => string

/** Who asked for a task: an MCP client ("agent"), Ask to the Wizard ("wizard"), or anyone else (""). */
export type TaskOrigin = 'agent' | 'wizard' | ''

export const AGENT_TARGET_KINDS = [
  'world3d_template', 'world3d_scene', 'scene_file', 'character_kit', 'series_episode', 'series',
  'story', 'montage', 'template', 'workspace_collection', 'file',
] as const
export type AgentTargetKind = typeof AGENT_TARGET_KINDS[number]

/** One artifact an agent created or changed, as recorded by the server (services/agent_activity.py). */
export interface AgentTarget {
  kind: AgentTargetKind
  id: string
  title?: string
  file?: string
  editor?: string
  series?: string
}

const KINDS = new Set<string>(AGENT_TARGET_KINDS)

function metadataOf(task: ActivityTaskLike): Record<string, unknown> {
  const metadata = task.metadata
  return metadata && typeof metadata === 'object' && !Array.isArray(metadata) ? metadata : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function taskOrigin(task: ActivityTaskLike): TaskOrigin {
  const metadata = metadataOf(task)
  // A Wizard change is an ``agent`` trail row too (services/agent_activity.py record_wizard): its tool says whose.
  if (metadata.tool === 'wizard' || metadata.actor === 'wizard') return 'wizard'
  if (task.kind === 'agent' || metadata.tool === 'external_agent' || metadata.actor === 'agent') return 'agent'
  return ''
}

export function groupOrigin(group: ActivityGroup): TaskOrigin {
  const origins = [group.primary, ...group.jobs.map(job => job.task)].map(taskOrigin)
  if (origins.includes('agent')) return 'agent'
  if (origins.includes('wizard')) return 'wizard'
  return ''
}

/** The MCP tool (or Wizard capability) that made the task, e.g. ``world3d.scene.patch``. */
export function taskCapability(task: ActivityTaskLike): string {
  return text(metadataOf(task).capability)
}

export function isAgentChange(task: ActivityTaskLike): boolean {
  return task.kind === 'agent' && metadataOf(task).adapter === 'agent'
}

function asTarget(value: unknown): AgentTarget | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const kind = text(record.kind)
  const id = text(record.id)
  if (!KINDS.has(kind) || !id) return null
  const target: AgentTarget = { kind: kind as AgentTargetKind, id }
  for (const key of ['title', 'file', 'editor', 'series'] as const) {
    const field = text(record[key])
    if (field) target[key] = field
  }
  return target
}

export function agentTargets(task: ActivityTaskLike): AgentTarget[] {
  const raw = metadataOf(task).targets
  if (!Array.isArray(raw)) return []
  return raw.map(asTarget).filter((item): item is AgentTarget => Boolean(item))
}

/** How many times each tool touched the artifact, newest entry last: ``[["world3d.scene.patch", 3], …]``. */
export function agentOperations(task: ActivityTaskLike): Array<[string, number]> {
  const raw = metadataOf(task).operations
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return []
  return Object.entries(raw as Record<string, unknown>)
    .map(([name, count]) => [name, Math.max(1, Number(count) || 1)] as [string, number])
}

export function filterGroupsByOrigin(groups: ActivityGroup[], origin: 'all' | 'agents'): ActivityGroup[] {
  if (origin === 'all') return groups
  return groups.filter(group => groupOrigin(group) !== '')
}

/** "Started by …": the agent tool or the Wizard when they asked, otherwise the Studio/Director label. */
export function initiatorText(t: Translate, task: ActivityTaskLike): string {
  const origin = taskOrigin(task)
  if (origin === 'agent') return t('origin.startedByAgent', { capability: taskCapability(task) || task.workflow || '' })
  if (origin === 'wizard') return t('origin.startedByWizard')
  const initiator = generationInitiator(task)
  return initiator ? t('startedBy', { name: initiator }) : ''
}

/** Files an agent change opens through its targets (so the generic artifact buttons skip them). */
export function targetFiles(task: ActivityTaskLike): Set<string> {
  return new Set(agentTargets(task).map(target => target.file).filter((file): file is string => Boolean(file)))
}

/** The row title of an agent change: what kind of artifact it is and its name, in the UI language. */
export function agentChangeTitle(t: Translate, task: ActivityTaskLike): string {
  if (!isAgentChange(task)) return ''
  const primary = agentTargets(task)[0]
  if (!primary) return ''
  return t(`agentTrail.kinds.${primary.kind}`, { name: primary.title || primary.file || primary.id })
}
