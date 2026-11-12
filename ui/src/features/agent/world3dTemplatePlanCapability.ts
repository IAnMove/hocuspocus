import type { defineCapability } from './capabilityRegistry'
import type { AgentWorld3DTemplatesAction } from './world3dTemplateCapabilities'
import i18n from '../../i18n'

/**
 * "Elige las tarjetas de Vídeo 3D de estos doce planos": world3d.templates.plan chooses the cards of a whole list of shots in one
 * call, with variety (no template twice in a row, one place keeps one family, alternates and the scene3d keys to copy). It is the
 * same operation as the MCP tool and the REST command; the Wizard runs it through the world3dTemplates adapter and lists
 * key | id | title | shot | why. Read-only: nothing is instantiated.
 */
export const WORLD3D_PLAN_OPERATION = 'world3d.templates.plan' as const

const SHOT_SIZES = ['close', 'medium', 'wide', 'far', 'plate'] as const
const MAX_SHOTS = 60

export interface PlanShotInput {
  key: string
  text?: string
  speakers?: number
  subjects?: number
  place?: string
  shot?: typeof SHOT_SIZES[number]
  moving?: boolean
}

export interface AgentPlan3DTemplatesAction {
  type: 'plan_3d_templates'
  shots: PlanShotInput[]
  format?: 'landscape' | 'portrait'
  avoid?: string[]
  perShot?: number
  seed?: number
}

type Card = Record<string, unknown>
const text = (value: unknown, max: number): string => typeof value === 'string' ? value.trim().slice(0, max) : ''
const whole = (value: unknown, low: number, high: number): number | undefined =>
  typeof value === 'number' && Number.isInteger(value) && value >= low && value <= high ? value : undefined

function planShot(raw: unknown, index: number): PlanShotInput | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const item = raw as Record<string, unknown>
  const [speakers, subjects] = [whole(item.speakers, 0, 4), whole(item.subjects, 0, 2)]
  const [line, place] = [text(item.text, 400), text(item.place, 120)]
  const size = SHOT_SIZES.find(name => name === item.shot)
  return {
    key: text(item.key, 80) || `s${index + 1}`,
    ...(line ? { text: line } : {}), ...(speakers !== undefined ? { speakers } : {}), ...(subjects !== undefined ? { subjects } : {}),
    ...(place ? { place } : {}), ...(size ? { shot: size } : {}), ...(typeof item.moving === 'boolean' ? { moving: item.moving } : {}),
  }
}

/** The request body of the operation: the same fields as the MCP tool, left out when empty. */
export function planInput(action: AgentPlan3DTemplatesAction): Record<string, unknown> {
  return {
    shots: action.shots,
    ...(action.format ? { format: action.format } : {}), ...(action.avoid?.length ? { avoid: action.avoid } : {}),
    ...(action.perShot !== undefined ? { per_shot: action.perShot } : {}), ...(action.seed !== undefined ? { seed: action.seed } : {}),
  }
}

/** One line per shot, «key | id | title | shot | why», then what the plan could not do and how much it repeats. */
export function world3dPlanMessage(result: Record<string, unknown>): string {
  const plan = (Array.isArray(result.plan) ? result.plan : []) as Array<Record<string, unknown>>
  const lines = plan.map(entry => {
    const primary = entry.primary as Card | null
    return primary ? [entry.key, primary.id, primary.title, primary.shot, primary.why].map(part => String(part ?? '')).join(' | ') : `${entry.key} | -`
  })
  const warnings = plan.flatMap(entry => (Array.isArray(entry.warnings) ? entry.warnings : [])
    .map(warning => i18n.t('wizard:replies.world3dPlanWarning', { key: String(entry.key), warning: String(warning) })))
  const summary = result.summary as { templates_used?: number, repeats?: number } | undefined
  const closing = summary ? i18n.t('wizard:replies.world3dPlanSummary', { used: summary.templates_used ?? 0, repeats: summary.repeats ?? 0 }) : ''
  const body = i18n.t('wizard:replies.world3dPlan', { count: plan.length, lines: lines.join('\n') })
  return [body, ...warnings, closing].filter(Boolean).join('\n')
}

export function registerWorld3DTemplatePlanCapabilities(register: typeof defineCapability) {
  register<AgentPlan3DTemplatesAction>({
    name: 'plan_3d_templates',
    title: 'Choose the Video 3D cards of every shot of a video at once',
    description: 'Read-only. Call it ONCE with every shot of the video instead of searching shot by shot: shots [{key, text, speakers, subjects, place, shot, moving}] (text is the shot as a writer phrases it; speakers 0 an establishing shot, 1 a talk shot, 2 or more a dialogue; subjects the subject slots the cast needs; omit what you do not know). The server ranks every shot with the shot library search, then chooses down the list: no card twice in a row, none more than twice, shot sizes and camera moves alternating, shots at one place keeping one stage or world with another camera each time, avoid ids never taken. format portrait takes portrait cards and, when too few fit, landscape cards marked adapted. Each shot gets a primary and alternates (per_shot 1 to 3) with the scene3d keys to copy (template, roomCamera, world). A different seed gives another valid plan. Use world3d_templates only to look at or replace one shot afterwards; never invent a template id.',
    useWhen: 'The user wants Video 3D cards for several or all the shots of a video, a shot list, a script or a Series episode, or asks for variety across shots ("elige las plantillas 3D de los doce planos", "cambia el plan para que no se repita").',
    parameters: ['shots', 'format', 'avoid', 'per_shot', 'seed'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'plan_3d_templates' },
        shots: {
          type: 'array', minItems: 1, maxItems: MAX_SHOTS,
          items: {
            type: 'object', additionalProperties: false, required: ['key'],
            properties: {
              key: { type: 'string', maxLength: 80 }, text: { type: 'string', maxLength: 400 },
              speakers: { type: 'integer', minimum: 0, maximum: 4 }, subjects: { type: 'integer', minimum: 0, maximum: 2 },
              place: { type: 'string', maxLength: 120 }, shot: { enum: [...SHOT_SIZES] }, moving: { type: 'boolean' },
            },
          },
        },
        format: { enum: ['landscape', 'portrait'] },
        avoid: { type: 'array', maxItems: 1000, items: { type: 'string', maxLength: 120 } },
        per_shot: { type: 'integer', minimum: 1, maximum: 3 },
        seed: { type: 'integer', minimum: 0, maximum: 2147483647 },
      },
      required: ['type', 'shots'],
    },
    risk: 'read', confirmation: 'none', progress: 'wizard:progress.planningVideo3dShots',
    resolve(raw) {
      const shots = (Array.isArray(raw.shots) ? raw.shots : []).slice(0, MAX_SHOTS).map(planShot).filter((shot): shot is PlanShotInput => shot !== null)
      if (!shots.length) return null
      const avoid = (Array.isArray(raw.avoid) ? raw.avoid : []).map(item => text(item, 120)).filter(Boolean)
      const [perShot, seed] = [whole(raw.per_shot, 1, 3), whole(raw.seed, 0, 2147483647)]
      return {
        type: 'plan_3d_templates', shots,
        ...(raw.format === 'landscape' || raw.format === 'portrait' ? { format: raw.format } : {}),
        ...(avoid.length ? { avoid } : {}), ...(perShot !== undefined ? { perShot } : {}), ...(seed !== undefined ? { seed } : {}),
      }
    },
    validate(action) {
      const keys = action.shots.map(shot => shot.key)
      return new Set(keys).size === keys.length ? [] : ['Give every shot its own key.']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      const plan: AgentWorld3DTemplatesAction = { type: 'world3d_templates', operation: WORLD3D_PLAN_OPERATION, input: planInput(action) }
      return context.adapters.world3dTemplates.command(plan, context.workspace)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_3d_scene', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: [] },
  })
}
