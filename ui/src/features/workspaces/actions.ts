import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'

const normalized = (value: string): string => value.trim().toLocaleLowerCase()

function workspaceResult(name: string, message: string): CommandResult {
  const entity = { kind: 'workspace', id: name, workspaceId: name }
  return commandResultFromSlice({
    entity,
    artifacts: [{
      id: 'reply',
      kind: 'document',
      owner: entity,
      uri: 'workspace:reply',
      metadata: { summary: message, title: name },
    }],
  })
}

function summaryOf(result: CommandResult): string {
  const summary = result.artifacts[0]?.metadata?.summary
  return typeof summary === 'string' ? summary : 'Workspace ready.'
}

async function authoritativeWorkspaces() {
  const result = await api.fetchWorkspaces()
  useStore.setState({ workspaces: result.workspaces })
  return result
}

export async function selectAgentWorkspace(requestedName: string): Promise<CommandResult> {
  if (requestedName === '__uploads__') {
    throw new Error('Uploads is a read-only virtual view, not a workspace you can select for generation.')
  }
  const before = await authoritativeWorkspaces()
  const workspace = before.workspaces.find(item => normalized(item.name) === normalized(requestedName))
  if (!workspace) {
    throw new Error(`There is no workspace “${requestedName}”. Available: ${before.workspaces.map(item => item.name).join(', ') || 'none'}.`)
  }
  if (before.active === workspace.name && useStore.getState().activeWorkspace === workspace.name) {
    return workspaceResult(workspace.name, `The workspace “${workspace.name}” was already active.`)
  }
  await useStore.getState().switchWorkspace(workspace.name)
  const after = await api.fetchWorkspaces()
  if (after.active !== workspace.name || useStore.getState().activeWorkspace !== workspace.name) {
    throw new Error(`The backend did not confirm the switch to workspace “${workspace.name}”; I won't claim it completed.`)
  }
  return workspaceResult(
    workspace.name,
    `I switched to workspace “${workspace.name}”. The chat and next actions continue in that context.`,
  )
}

export async function createAgentWorkspace(requestedName: string): Promise<CommandResult> {
  const name = requestedName.trim()
  if (!name || name === '__uploads__') throw new Error('That workspace name is not valid.')
  const before = await authoritativeWorkspaces()
  const existing = before.workspaces.find(item => normalized(item.name) === normalized(name))
  if (existing) {
    const selected = await selectAgentWorkspace(existing.name)
    return workspaceResult(
      existing.name,
      `The workspace “${existing.name}” already existed. ${summaryOf(selected)}`,
    )
  }
  await useStore.getState().createWorkspace(name)
  const after = await api.fetchWorkspaces()
  const created = after.workspaces.find(item => normalized(item.name) === normalized(name))
  if (!created || after.active !== created.name || useStore.getState().activeWorkspace !== created.name) {
    throw new Error(`The backend did not confirm creating and selecting “${name}”.`)
  }
  return workspaceResult(
    created.name,
    `I created and selected the workspace “${created.name}”. The chat continues here and new generations will be saved in it.`,
  )
}
