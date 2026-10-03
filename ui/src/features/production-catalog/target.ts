import type { CatalogProject } from './types'

export interface ReviewDetail {
  workspace: string
  productionId: string
}

export interface LinkedTarget {
  kind: 'story' | 'episode'
  id: string
  seriesId?: string
}

export function reviewDetail(workspace: string, productionId: string): ReviewDetail | null {
  const scope = workspace.trim()
  const production = productionId.trim()
  if (!scope || scope.length > 160 || !production || production.length > 240) return null
  return { workspace: scope, productionId: production }
}

export function linkedTarget(project: CatalogProject | null, seriesId: string | null): LinkedTarget | null {
  if (!project || !project.id || project.id.length > 160) return null
  if (project.kind === 'story') return { kind: 'story', id: project.id }
  if (project.kind === 'episode' && seriesId && seriesId.length <= 160) {
    return { kind: 'episode', id: project.id, seriesId }
  }
  return null
}
