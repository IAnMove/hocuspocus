import { recordWizardChange, type WizardChangeTarget } from '../../api/tasks'
import type { AgentExecutionReport, AgentExecutionTarget } from './agentContract'
import type { CapabilityRisk } from './capabilityRegistry'

/** Wizard report target kinds that name a saved artifact, and the trail kind that opens it (activity/agentOrigin.ts). */
const TRAIL_KINDS: Record<string, string> = {
  character_kit: 'character_kit',
  story: 'story',
  series_episode: 'series_episode',
  series: 'series',
  workspace_collection: 'workspace_collection',
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function reportTarget(target: AgentExecutionTarget | undefined): WizardChangeTarget | null {
  if (!target?.id) return null
  if (target.kind === 'output') {
    return { kind: 'file', id: target.id, file: target.id, ...(target.title ? { title: target.title } : {}) }
  }
  if (target.kind === 'video_3d_scene' && /^w3d-[0-9a-f]{12}$/.test(target.id)) {
    return { kind: 'world3d_scene', id: target.id, ...(target.title ? { title: target.title } : {}) }
  }
  const kind = TRAIL_KINDS[target.kind]
  return kind ? { kind, id: target.id, ...(target.title ? { title: target.title } : {}) } : null
}

/** A Video 3D template command's result names a saved personal template or a published scene file. */
function world3dResultTargets(metadata: Record<string, unknown> | undefined): WizardChangeTarget[] {
  const result = record(record(metadata).result)
  const template = record(result.template)
  const scene = record(result.scene)
  const found: WizardChangeTarget[] = []
  if (text(template.id).startsWith('user-')) {
    found.push({ kind: 'world3d_template', id: text(template.id), ...(text(template.title) ? { title: text(template.title) } : {}) })
  }
  const file = text(scene.file)
  if (file.endsWith('.world3d.scene.json')) found.push({ kind: 'scene_file', id: file, file, editor: 'video3d' })
  return found
}

/** What a Wizard capability changed that the user should find again: the artifacts its report names. Pure. */
export function wizardTrailTargets(report: Pick<AgentExecutionReport, 'target' | 'projectTarget' | 'metadata' | 'state'>): WizardChangeTarget[] {
  if (report.state === 'failed' || report.state === 'awaiting_input') return []
  const found = [reportTarget(report.target), reportTarget(report.projectTarget), ...world3dResultTargets(report.metadata)]
  const unique = new Map<string, WizardChangeTarget>()
  for (const target of found) if (target) unique.set(`${target.kind}:${target.id}`, { ...unique.get(`${target.kind}:${target.id}`), ...target })
  return [...unique.values()]
}

/** The series an episode belongs to, so its trail button opens Series Lab on it. */
async function withSeries(targets: WizardChangeTarget[]): Promise<WizardChangeTarget[]> {
  if (!targets.some(target => target.kind === 'series_episode' && !target.series)) return targets
  const { useSeriesStore } = await import('../series/store')
  const library = useSeriesStore.getState().library
  return targets.map(target => {
    if (target.kind !== 'series_episode' || target.series) return target
    const series = Object.values(library.seriesById).find(item => Boolean(item.episodesById?.[target.id]))
    return series ? { ...target, series: series.id } : target
  })
}

/**
 * After an ``edit`` or ``compute`` capability, give what it changed a row in Activity's Agents view, like an MCP
 * agent's change (the jobs it started are already badged Wizard). Never throws: the trail must not fail the Wizard.
 */
export async function reportWizardChange(input: {
  workspace: string
  capability: string
  commandId: string
  risk: CapabilityRisk
  report: Pick<AgentExecutionReport, 'target' | 'projectTarget' | 'metadata' | 'state'>
}): Promise<boolean> {
  if (input.risk !== 'edit' && input.risk !== 'compute') return false
  try {
    const targets = await withSeries(wizardTrailTargets(input.report))
    if (!targets.length) return false
    return await recordWizardChange({ workspace: input.workspace || 'default', capability: input.capability, commandId: input.commandId, targets })
  } catch {
    return false
  }
}
