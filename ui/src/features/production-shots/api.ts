import type { ShotView } from './types'

export async function loadShotView(workspace: string, productionId: string): Promise<ShotView> {
  const target = `/api/v1/production-projects/${encodeURIComponent(productionId)}/shots?workspace=${encodeURIComponent(workspace)}`
  const response = await fetch(target)
  if (!response.ok) throw new Error(String(response.status))
  return response.json() as Promise<ShotView>
}
