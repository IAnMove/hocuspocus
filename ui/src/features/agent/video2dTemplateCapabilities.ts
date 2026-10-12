import type { defineCapability } from './capabilityRegistry'

/**
 * Video 2D music cards for a production shot. scenes.templates.suggest ranks the music-* cards (the cutout
 * choreographies and the music originals) for a line, its speakers, mood, beat and format; scenes.catalog searches
 * the 2D catalogs or opens one card by id. Both are read-only: they post to /api/v1/scenes/templates/commands, the
 * same handlers the MCP tools of the same names run, and nothing is created.
 */
export const VIDEO2D_TEMPLATE_OPERATIONS = [
  'scenes.templates.suggest',
  'scenes.catalog',
] as const

export type Video2DTemplateOperation = typeof VIDEO2D_TEMPLATE_OPERATIONS[number]

export interface AgentVideo2DTemplatesAction {
  type: 'video2d_templates'
  operation: Video2DTemplateOperation
  input: Record<string, unknown>
}

type Card = Record<string, unknown>
type Video2DReply = { status?: string, result?: Record<string, unknown>, detail?: { message?: string } | string }

const operations = new Set<string>(VIDEO2D_TEMPLATE_OPERATIONS)

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** The rows of a reply: suggest's cards or a catalog page, whatever key the operation answers with. */
function cardsOf(result: Record<string, unknown>): Card[] {
  for (const key of ['templates', 'cards', 'suggestions', 'entries']) {
    const value = result[key]
    if (Array.isArray(value)) return value.filter((item): item is Card => !!item && typeof item === 'object')
  }
  const entry = result.entry
  return entry && typeof entry === 'object' && !Array.isArray(entry) ? [entry as Card] : []
}

export function video2dTemplateMessage(reply: Video2DReply): string {
  const result = reply.result || {}
  const lines = cardsOf(result).slice(0, 8).map(card => {
    const title = text(card.titleEs) || text(card.title) || text(card.name)
    const why = text(card.reason) || text(card.lineEs) || text(card.description)
    return [text(card.id), title, text(card.titleEn), why].filter(Boolean).join(' | ')
  })
  const unknown = Array.isArray(result.unknown_words) ? result.unknown_words.map(text).filter(Boolean) : []
  const missing = unknown.length ? `\nNinguna carta conoce: ${unknown.join(', ')}.` : ''
  if (!lines.length) return `Ninguna carta 2D coincide.${missing}`
  return `${lines.join('\n')}${missing}`
}

export async function executeVideo2DTemplates(action: AgentVideo2DTemplatesAction) {
  const response = await fetch('/api/v1/scenes/templates/commands', {
    method: 'POST', headers: { 'content-type': 'application/json', 'X-Hocus-UI-Surface': 'wizard' },
    body: JSON.stringify({ operation: action.operation, version: 1, input: action.input }),
  })
  const reply = await response.json() as Video2DReply
  if (!response.ok) {
    throw new Error(typeof reply.detail === 'string' ? reply.detail : reply.detail?.message || `${action.operation} failed`)
  }
  const first = cardsOf(reply.result || {})[0]
  return {
    message: video2dTemplateMessage(reply),
    metadata: reply as Record<string, unknown>,
    target: { kind: 'video_2d_template', id: text(first?.id) || action.operation, title: action.operation },
  }
}

export function registerVideo2DTemplateCapabilities(register: typeof defineCapability) {
  register<AgentVideo2DTemplatesAction>({
    name: 'video2d_templates',
    title: 'Find a Video 2D music card for a production shot',
    description: 'Read-only. scenes.templates.suggest {line, speakers, mood, beat, format, limit} returns up to three music-* cards (cutout choreographies on the beat and the music originals) with a reason and unknown_words; scenes.catalog {kind: "templates", q, id, use, move, subjects, format} searches or opens one card with its slots and controls. Never invent a card id.',
    useWhen: 'The user wants a cutout choreography, a figure that dances or bounces on the beat, or a Video 2D card for a music-video shot.',
    parameters: ['operation', 'input'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'video2d_templates' },
        operation: { enum: [...VIDEO2D_TEMPLATE_OPERATIONS] },
        input: { type: 'object' },
      },
      required: ['type', 'operation', 'input'],
    },
    risk: 'read', confirmation: 'none', progress: 'Buscando cartas de Vídeo 2D…',
    resolve(raw) {
      if (typeof raw.operation !== 'string' || !operations.has(raw.operation) || !raw.input || typeof raw.input !== 'object' || Array.isArray(raw.input)) return null
      return { type: 'video2d_templates', operation: raw.operation as Video2DTemplateOperation, input: raw.input as Record<string, unknown> }
    },
    validate(action) { return operations.has(action.operation) ? [] : ['Choose a Video 2D template operation.'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.video2dTemplates.command(action) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_2d_template', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: [] },
  })
}
