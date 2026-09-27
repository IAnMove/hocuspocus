import { asMap, firstText, text } from './fields.ts'
import type { ActivityOpenSource, ReviewDesk } from './types.ts'

const PRODUCTION_KINDS = new Set([
  'production',
  'director_production',
  'pipeline',
  'story_production',
])

function metadataOf(source: ActivityOpenSource): Record<string, unknown> {
  const own = asMap(source.metadata)
  const primary = asMap(source.primary?.metadata)
  return { ...primary, ...own }
}

function kindOf(source: ActivityOpenSource, metadata: Record<string, unknown>): string {
  return firstText(
    source.kind,
    source.project?.kind,
    metadata.entity_type,
    metadata.project_kind,
    metadata.target_kind,
  )
}

function idWhenProductionKind(kind: string, source: ActivityOpenSource, metadata: Record<string, unknown>): string {
  if (!PRODUCTION_KINDS.has(kind) && kind !== '') return ''
  return firstText(
    metadata.production_id,
    metadata.entity_id,
    metadata.pipeline_id,
    source.pipeline_id,
    source.primary?.pipeline_id,
    source.id,
    source.project?.id,
  )
}

export function productionIdFromActivity(source: ActivityOpenSource | null | undefined): string | null {
  if (!source) return null
  const metadata = metadataOf(source)
  const kind = kindOf(source, metadata)
  const fromKind = idWhenProductionKind(kind, source, metadata)
  if (fromKind) return fromKind
  return firstText(
    metadata.production_id,
    metadata.pipeline_id,
    source.pipeline_id,
    source.primary?.pipeline_id,
  ) || null
}

export function isSameProduction(desk: ReviewDesk, source: ActivityOpenSource | null | undefined): boolean {
  const id = productionIdFromActivity(source)
  if (!id) return false
  return id === desk.productionId || id === desk.pipelineId
}

export function openReviewFromActivity(
  desk: ReviewDesk,
  source: ActivityOpenSource | null | undefined,
): { same: boolean; productionId: string } | null {
  const productionId = productionIdFromActivity(source)
  if (!productionId) return null
  const same = productionId === desk.productionId || productionId === desk.pipelineId
  return { same, productionId }
}

export function activitySourceFromGroup(group: {
  project?: { kind?: string; id?: string }
  primary?: { pipeline_id?: string; metadata?: Record<string, unknown> }
}): ActivityOpenSource {
  return {
    kind: text(group.project?.kind),
    id: text(group.project?.id),
    project: group.project,
    pipeline_id: group.primary?.pipeline_id,
    primary: group.primary,
    metadata: group.primary?.metadata,
  }
}
