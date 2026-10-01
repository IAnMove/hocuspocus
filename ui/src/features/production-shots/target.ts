export type ShotTarget = { workspace: string; productionId: string }

export function shotTarget(detail: unknown): ShotTarget | null {
  if (!detail || typeof detail !== 'object') return null
  const record = detail as { workspace?: unknown; productionId?: unknown }
  const workspace = typeof record.workspace === 'string' ? record.workspace.trim() : ''
  const productionId = typeof record.productionId === 'string' ? record.productionId.trim() : ''
  if (!workspace || !productionId || workspace.length > 160 || productionId.length > 240) return null
  return { workspace, productionId }
}
