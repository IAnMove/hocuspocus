import { createAgentWorkspace, selectAgentWorkspace } from './actions'
import type { CreateWorkspaceCommand, SelectWorkspaceCommand } from './commands'

export async function selectWorkspace(command: SelectWorkspaceCommand): Promise<string> {
  return selectAgentWorkspace(command.workspaceName)
}

export async function createWorkspace(command: CreateWorkspaceCommand): Promise<string> {
  return createAgentWorkspace(command.workspaceName)
}
