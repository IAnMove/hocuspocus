import type { CatalogPage } from './types'

async function postCommand(body: Record<string, unknown>): Promise<CatalogPage> {
  const response = await fetch('/api/v1/production-projects/commands', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ version: 1, ...body }),
  })
  if (!response.ok) throw new Error(String(response.status))
  return response.json() as Promise<CatalogPage>
}

export async function listWorks(workspace: string, format: string, status: string): Promise<CatalogPage> {
  return postCommand({
    operation: 'production.works.list',
    input: { workspace, format, status },
  })
}

export async function resolveWork(workspace: string, input: { intent_id: string, format: string, title: string }): Promise<void> {
  const response = await fetch('/api/v1/production-projects/resolve', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ workspace, origin: 'ui', new_execution: false, ...input }),
  })
  if (!response.ok) throw new Error(String(response.status))
}

export async function linkWork(
  workspace: string,
  productionId: string,
  project: { kind: 'story' | 'episode', id: string },
): Promise<void> {
  await postCommand({
    operation: 'production.works.link',
    input: { workspace, production_id: productionId, project },
  })
}
