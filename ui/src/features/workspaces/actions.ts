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
  return typeof summary === 'string' ? summary : 'Workspace listo.'
}

async function authoritativeWorkspaces() {
  const result = await api.fetchWorkspaces()
  useStore.setState({ workspaces: result.workspaces })
  return result
}

export async function selectAgentWorkspace(requestedName: string): Promise<CommandResult> {
  if (requestedName === '__uploads__') {
    throw new Error('Uploads es una vista virtual de sólo lectura, no un workspace seleccionable para generar.')
  }
  const before = await authoritativeWorkspaces()
  const workspace = before.workspaces.find(item => normalized(item.name) === normalized(requestedName))
  if (!workspace) {
    throw new Error(`No existe el workspace “${requestedName}”. Los disponibles son: ${before.workspaces.map(item => item.name).join(', ') || 'ninguno'}.`)
  }
  if (before.active === workspace.name && useStore.getState().activeWorkspace === workspace.name) {
    return workspaceResult(workspace.name, `El workspace “${workspace.name}” ya estaba activo.`)
  }
  await useStore.getState().switchWorkspace(workspace.name)
  const after = await api.fetchWorkspaces()
  if (after.active !== workspace.name || useStore.getState().activeWorkspace !== workspace.name) {
    throw new Error(`El backend no confirmó el cambio al workspace “${workspace.name}”; no afirmaré que se completó.`)
  }
  return workspaceResult(
    workspace.name,
    `He cambiado al workspace “${workspace.name}”. El chat y las siguientes acciones continúan en ese contexto.`,
  )
}

export async function createAgentWorkspace(requestedName: string): Promise<CommandResult> {
  const name = requestedName.trim()
  if (!name || name === '__uploads__') throw new Error('Ese nombre de workspace no es válido.')
  const before = await authoritativeWorkspaces()
  const existing = before.workspaces.find(item => normalized(item.name) === normalized(name))
  if (existing) {
    const selected = await selectAgentWorkspace(existing.name)
    return workspaceResult(
      existing.name,
      `El workspace “${existing.name}” ya existía. ${summaryOf(selected)}`,
    )
  }
  await useStore.getState().createWorkspace(name)
  const after = await api.fetchWorkspaces()
  const created = after.workspaces.find(item => normalized(item.name) === normalized(name))
  if (!created || after.active !== created.name || useStore.getState().activeWorkspace !== created.name) {
    throw new Error(`El backend no confirmó la creación y selección de “${name}”.`)
  }
  return workspaceResult(
    created.name,
    `He creado y seleccionado el workspace “${created.name}”. El chat continúa aquí y las nuevas generaciones se guardarán en él.`,
  )
}
