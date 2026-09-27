import type { AgentTab } from './agentActions'
import type { AgentExecutionReport, AgentExecutionState, AgentExecutionTarget } from './agentContract'

export interface WizardExecutionCardControls {
  open: boolean
  cancel: boolean
  resume: boolean
  viewErrors: boolean
  retryPending: boolean
}

export interface WizardExecutionCard extends AgentExecutionReport {
  id: string
  controls: WizardExecutionCardControls
}

const RUNNING: AgentExecutionState[] = ['queued', 'running']
const RECOVERABLE: AgentExecutionState[] = ['partial', 'failed']

export function cardFromReport(report: AgentExecutionReport, id?: string): WizardExecutionCard {
  const running = RUNNING.includes(report.state)
  const recoverable = report.recoverable || RECOVERABLE.includes(report.state)
  const taskControls = Boolean(executionCardTaskId(report)) && report.target?.kind !== 'wizard_workflow'
  return {
    ...report,
    id: id || report.executionKey || report.taskId || report.pipelineId || report.message,
    controls: {
      open: canOpenExecutionCard(report),
      cancel: taskControls && running,
      resume: taskControls && recoverable && RECOVERABLE.includes(report.state),
      viewErrors: report.state === 'failed' || report.state === 'partial',
      retryPending: taskControls && RECOVERABLE.includes(report.state),
    },
  }
}

function canOpenExecutionCard(report: AgentExecutionReport): boolean {
  if (report.target?.kind === 'activity') return true
  if (report.target?.kind === 'wizard_workflow') return Boolean(executionCardTaskId(report))
  return Boolean(tabForExecutionTarget(report.target))
}

export function cardsFromResults(results: Array<{ report?: AgentExecutionReport }>): WizardExecutionCard[] {
  return results.flatMap(result => result.report ? [cardFromReport(result.report)] : [])
}

export function applyPollToCard(card: WizardExecutionCard, update: Partial<AgentExecutionReport>): WizardExecutionCard {
  return cardFromReport({
    ...card,
    ...update,
    message: update.message || card.message,
    outputNames: update.outputNames || card.outputNames,
    assetIds: update.assetIds || card.assetIds,
  }, card.id)
}

/** Card buttons must never turn a missing receipt into a queue-wide selector. */
export function executionCardTaskId(report: Pick<AgentExecutionReport, 'taskId'>): string | null {
  const id = report.taskId?.trim()
  return id && !/\s/.test(id) && !['latest', 'active', 'current'].includes(id) ? id : null
}

const APPLICATION_TABS = new Set<AgentTab>([
  'studio', 'director', 'productions', 'images', 'videos', 'audio', '3d', 'story_lab',
  'series_lab', 'comics', 'video_editor', 'video_3d', 'animate_3d', 'character_creator',
  'character_kit', 'workspaces', 'settings',
])

export function tabForExecutionTarget(target?: AgentExecutionTarget): AgentTab | null {
  if (target?.kind === 'application_section') {
    return APPLICATION_TABS.has(target.id as AgentTab) ? target.id as AgentTab : null
  }
  switch (target?.kind) {
    case 'comic': return 'comics'
    case 'director_production': return 'director'
    case 'story': return 'story_lab'
    case 'series':
    case 'series_episode': return 'series_lab'
    case 'scene': return 'video_3d'
    case 'character_kit': return 'character_kit'
    case 'video_editor': return 'video_editor'
    case 'workspace_collection': return 'workspaces'
    default: return null
  }
}
