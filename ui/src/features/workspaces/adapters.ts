import { createAgentWorkspace, selectAgentWorkspace } from './actions'
import type { CreateWorkspaceCommand, SelectWorkspaceCommand } from './commands'

export async function selectWorkspace(command: SelectWorkspaceCommand) {
  return selectAgentWorkspace(command.workspaceName)
}

export async function createWorkspace(command: CreateWorkspaceCommand) {
  return createAgentWorkspace(command.workspaceName)
}
