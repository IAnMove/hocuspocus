import type { defineCapability } from './capabilityRegistry'
import { openSharedShots } from '../production-catalog/openShots'
import { REVIEW_EVENT } from '../production-catalog/reviewEvent'

export const PRODUCTION_WORK_OPERATIONS = [
  'production.works.list',
  'production.works.open',
  'production.works.resolve',
  'production.works.link',
] as const

export type ProductionWorkOperation = typeof PRODUCTION_WORK_OPERATIONS[number]

export interface AgentProductionWorksAction {
  type: 'production_works'
  operation: ProductionWorkOperation
  input: Record<string, unknown>
}

const operations = new Set<string>(PRODUCTION_WORK_OPERATIONS)

export function productionWorksMessage(body: {
  applied?: boolean
  reused?: boolean
  production_id?: string
  works?: Array<{ production_id?: string, origin?: string, project?: { id?: string } | null }>
  work?: { production_id?: string, review?: { event?: string, workspace?: string, production_id?: string } }
  review?: { event?: string, workspace?: string, production_id?: string, project?: { kind?: string, id?: string } }
}): string {
  const review = body.work?.review || body.review
  const listed = (body.works || []).map(item => `${item.production_id || ''} ${item.origin || ''} ${item.project?.id || ''}`.trim())
  if (body.applied && body.reused) {
    return `Kept ${body.production_id || review?.production_id || ''}. Review ${review?.event || REVIEW_EVENT} in ${review?.workspace || ''}.`
  }
  if (body.applied) {
    return `Linked ${body.production_id || ''}. Review ${review?.event || REVIEW_EVENT} in ${review?.workspace || ''}.`
  }
  return `Found ${listed.length} works. Review ${REVIEW_EVENT}.\n${listed.join('\n')}`.trim()
}

export async function executeProductionWorks(
  action: AgentProductionWorksAction,
  workspace: string | undefined,
): Promise<{ message: string, metadata: Record<string, unknown>, target: { kind: string, id: string, title: string } }> {
  const active = typeof workspace === 'string' ? workspace : ''
  const input = { workspace: active, ...action.input }
  const response = await fetch('/api/v1/production-projects/commands', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ operation: action.operation, version: 1, input }),
  })
  const body = await response.json() as Parameters<typeof productionWorksMessage>[0] & { detail?: { message?: string } }
  if (!response.ok) throw new Error(body.detail?.message || 'Production works command failed')
  const review = body.work?.review || body.review
  if (action.operation !== 'production.works.list' && review?.workspace && review.production_id) {
    openSharedShots(review.workspace, review.production_id)
  }
  const productionId = body.production_id || review?.production_id || 'works'
  return {
    message: productionWorksMessage(body),
    metadata: body as Record<string, unknown>,
    target: { kind: 'production', id: productionId, title: action.operation },
  }
}

export function registerProductionWorkCapabilities(register: typeof defineCapability) {
  register<AgentProductionWorksAction>({
    name: 'production_works',
    title: 'Find a production and open its shots',
    description: 'List works in one workspace, open one production, or link a light Story before review. Does not start a generator. The same intent keeps the same production.',
    useWhen: 'The user asks where a music video, trailer, or video went, or wants to review its shots.',
    parameters: ['operation', 'input'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'production_works' },
        operation: { enum: [...PRODUCTION_WORK_OPERATIONS] },
        input: { type: 'object' },
      },
      required: ['type', 'operation', 'input'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Buscando la obra…',
    resolve(raw) {
      if (typeof raw.operation !== 'string' || !operations.has(raw.operation) || !raw.input || typeof raw.input !== 'object' || Array.isArray(raw.input)) return null
      return { type: 'production_works', operation: raw.operation as ProductionWorkOperation, input: raw.input as Record<string, unknown> }
    },
    validate(action) { return operations.has(action.operation) ? [] : ['Choose a production works operation.'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.productionWorks.command(action, context.workspace)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'production', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'productions', anchors: ['production'], replay: 'atomic' },
  })
}
