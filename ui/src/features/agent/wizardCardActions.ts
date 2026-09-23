import type { AgentActionResult } from './agentActions'
import { executeAgentActions } from './agentActions'
import { cardFromReport, executionCardTaskId, tabForExecutionTarget, type WizardExecutionCard } from './executionCards'
import { openAgentActivityDetails } from './agentUiBus'
import { defaultWizardWorkflowRuntime as runtime, isServerOwnedWorkflow, type WizardWorkflowRecord } from './wizardWorkflowRuntime'
import { useStore } from '../../stores/useStore'

export type WizardCardControl = 'open' | 'cancel' | 'resume' | 'retry'

function localWorkflow(card: WizardExecutionCard, workspace: string): WizardWorkflowRecord | undefined {
  if (card.target?.kind !== 'wizard_workflow') return undefined
  const workflow = runtime.get(card.target.id)
  return workflow?.workspace === workspace && !isServerOwnedWorkflow(workflow) ? workflow : undefined
}

export function wizardCardControls(card: WizardExecutionCard, workspace: string) {
  const controls = cardFromReport(card, card.id).controls
  const workflow = localWorkflow(card, workspace)
  if (!workflow) return controls
  return { ...controls,
    cancel: ['prepared', 'queued', 'waiting', 'running', 'awaiting_input', 'retrying'].includes(workflow.state),
    resume: ['failed', 'partial', 'cancelled'].includes(workflow.state),
  }
}

function workflowStepTaskId(workflow: WizardWorkflowRecord | undefined): string | null {
  if (!workflow) return null
  return executionCardTaskId({ taskId: workflow.steps[workflow.currentStep]?.taskId })
}

async function cancelWorkflow(workflow: WizardWorkflowRecord): Promise<AgentActionResult[]> {
  const knownTaskId = workflowStepTaskId(workflow)
  await runtime.cancel(workflow.workflowId)
  // `runtime.get` clones: the object we cancelled is stale. Read the live
  // checkpoint so a task id attached while execute() was in flight is stopped.
  const taskId = workflowStepTaskId(runtime.get(workflow.workflowId)) || knownTaskId
  if (!taskId) return []
  return executeAgentActions([{ type: 'cancel_task', taskId, confirm: true }], undefined, { workspace: workflow.workspace })
}

async function controlWorkflow(card: WizardExecutionCard, control: WizardCardControl, workspace: string): Promise<AgentActionResult[]> {
  const workflow = localWorkflow(card, workspace)
  if (!workflow) return []
  if (control === 'cancel') return cancelWorkflow(workflow)
  await runtime.resume(workflow.workflowId)
  return []
}

export async function executeWizardCardControl(card: WizardExecutionCard, control: WizardCardControl, workspace: string): Promise<AgentActionResult[]> {
  if ((useStore.getState().activeWorkspace || 'default') !== workspace) throw new Error('The workspace changed before the control could run.')
  if (control !== 'open' && card.target?.kind === 'wizard_workflow') return controlWorkflow(card, control, workspace)
  const taskId = executionCardTaskId(card)
  if (control === 'open') return openCard(card, taskId, workspace)
  if (!taskId) return []
  return executeAgentActions([{ type: control === 'cancel' ? 'cancel_task' : control === 'resume' ? 'resume_task' : 'retry_task', taskId, confirm: true }], undefined, { workspace })
}

async function openCard(card: WizardExecutionCard, taskId: string | null, workspace: string): Promise<AgentActionResult[]> {
  if (card.target?.kind === 'activity' || card.target?.kind === 'wizard_workflow') {
    openAgentActivityDetails({ taskId: taskId || undefined })
    return []
  }
  const tab = tabForExecutionTarget(card.target)
  return tab ? executeAgentActions([{ type: 'open_tab', tab }], undefined, { workspace }) : []
}
