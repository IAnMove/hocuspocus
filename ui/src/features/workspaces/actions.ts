import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import i18n from '../../i18n'
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
  return typeof summary === 'string' ? summary : i18n.t('workspaces:replies.ready')
}

async function authoritativeWorkspaces() {
  const result = await api.fetchWorkspaces()
  useStore.setState({ workspaces: result.workspaces })
  return result
}

export async function selectAgentWorkspace(requestedName: string): Promise<CommandResult> {
  if (requestedName === '__uploads__') {
    throw new Error(i18n.t('workspaces:actionErrors.uploadsReadOnly'))
  }
  const before = await authoritativeWorkspaces()
  const workspace = before.workspaces.find(item => normalized(item.name) === normalized(requestedName))
  if (!workspace) {
    const available = before.workspaces.map(item => item.name).join(', ') || i18n.t('workspaces:actionErrors.none')
    throw new Error(i18n.t('workspaces:actionErrors.missing', { name: requestedName, available }))
  }
  if (before.active === workspace.name && useStore.getState().activeWorkspace === workspace.name) {
    return workspaceResult(workspace.name, i18n.t('workspaces:replies.alreadyActive', { name: workspace.name }))
  }
  await useStore.getState().switchWorkspace(workspace.name)
  const after = await api.fetchWorkspaces()
  if (after.active !== workspace.name || useStore.getState().activeWorkspace !== workspace.name) {
    throw new Error(i18n.t('workspaces:actionErrors.switchUnconfirmed', { name: workspace.name }))
  }
  return workspaceResult(
    workspace.name,
    i18n.t('workspaces:replies.switched', { name: workspace.name }),
  )
}

export async function createAgentWorkspace(requestedName: string): Promise<CommandResult> {
  const name = requestedName.trim()
  if (!name || name === '__uploads__') throw new Error(i18n.t('workspaces:actionErrors.invalidName'))
  const before = await authoritativeWorkspaces()
  const existing = before.workspaces.find(item => normalized(item.name) === normalized(name))
  if (existing) {
    const selected = await selectAgentWorkspace(existing.name)
    return workspaceResult(
      existing.name,
      i18n.t('workspaces:replies.alreadyExisted', { name: existing.name, summary: summaryOf(selected) }),
    )
  }
  await useStore.getState().createWorkspace(name)
  const after = await api.fetchWorkspaces()
  const created = after.workspaces.find(item => normalized(item.name) === normalized(name))
  if (!created || after.active !== created.name || useStore.getState().activeWorkspace !== created.name) {
    throw new Error(i18n.t('workspaces:actionErrors.createUnconfirmed', { name }))
  }
  return workspaceResult(
    created.name,
    i18n.t('workspaces:replies.created', { name: created.name }),
  )
}
