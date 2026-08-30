import type { AgentTab } from './agentActions'
import type { AgentExecutionReport, AgentExecutionState } from './agentContract'

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
  return {
    ...report,
    id: id || report.executionKey || report.taskId || report.pipelineId || report.message,
    controls: {
      open: Boolean(report.target?.id || report.target?.kind),
      cancel: running,
      resume: recoverable && report.state !== 'running',
      viewErrors: report.state === 'failed' || report.state === 'partial',
      retryPending: report.state === 'partial' || report.state === 'failed',
    },
  }
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
  }, card.id)
}

export function tabForExecutionTarget(kind?: string): AgentTab {
  switch (kind) {
    case 'comic': return 'comics'
    case 'director_production': return 'director'
    case 'story': return 'story_lab'
    case 'series': return 'series_lab'
    case 'scene': return 'video_3d'
    case 'character_kit': return 'character_kit'
    case 'video_editor': return 'video_editor'
    default: return 'studio'
  }
}
