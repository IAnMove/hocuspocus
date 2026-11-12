import type { defineCapability } from './capabilityRegistry'
import i18n from '../../i18n'
import { makeRealCharacter, type RealGender } from '../../api/realCharacter'

/**
 * "Hazme un hombre de cuarenta años con traje", "cámbiale la ropa a Marta": one realistic PS2-era 3D person, made by the same server job
 * the Studio 3D panel «Realista (PS2)» and the model3d.real.make MCP tool start (POST /api/v1/model3d/real). Qwen paints the body and the
 * head from two English prompts, the character is rigged and a photo face kit talks. A make of a name already made keeps every field it
 * leaves out, so "change the clothes" sends only outfit_prompt. It takes minutes, so the Wizard starts it and says where to follow it.
 */
export interface AgentMakeRealCharacterAction {
  type: 'make_real_character'
  name: string
  gender?: RealGender
  skin?: string
  height?: number
  body?: string
  bottom?: string
  outfitPrompt?: string
  facePrompt?: string
  seed?: number
  talkKit?: boolean
  confirm: true
}

const GENDERS = ['man', 'woman']
const BODIES = ['slim', 'average', 'tall']
const BOTTOMS = ['trousers', 'skirt', 'shorts']
const HEX = /^#[0-9a-fA-F]{6}$/

const text = (value: unknown, limit: number): string => typeof value === 'string' ? value.trim().slice(0, limit) : ''
const choice = <T extends string>(value: unknown, allowed: string[]): T | undefined => typeof value === 'string' && allowed.includes(value) ? value as T : undefined

function numberIn(value: unknown, low: number, high: number, whole = false): number | undefined {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  return Number.isFinite(parsed) && parsed >= low && parsed <= high && (!whole || Number.isInteger(parsed)) ? parsed : undefined
}

function optional<K extends string, V>(key: K, value: V | undefined | ''): Partial<Record<K, V>> {
  return value === undefined || value === '' ? {} : { [key]: value } as Record<K, V>
}

export function resolveRealCharacter(raw: Record<string, unknown>): AgentMakeRealCharacterAction | null {
  const name = text(raw.name, 64)
  if (raw.confirm !== true || !name) return null
  const skin = typeof raw.skin === 'string' && HEX.test(raw.skin) ? raw.skin.toUpperCase() : undefined
  return {
    type: 'make_real_character', name, confirm: true,
    ...optional('gender', choice<RealGender>(raw.gender, GENDERS)), ...optional('skin', skin),
    ...optional('height', numberIn(raw.height_m, 1.2, 2.2)), ...optional('body', choice(raw.body, BODIES)), ...optional('bottom', choice(raw.bottom, BOTTOMS)),
    ...optional('outfitPrompt', text(raw.outfit_prompt, 1200)), ...optional('facePrompt', text(raw.face_prompt, 1200)),
    ...optional('seed', numberIn(raw.seed, 0, 2_147_483_647, true)),
    ...(raw.talk_kit === true || raw.talk_kit === false ? { talkKit: raw.talk_kit } : {}),
  }
}

export async function executeMakeRealCharacter(action: AgentMakeRealCharacterAction, workspace?: string) {
  const space = workspace || 'default' // executeAgentActions always passes the workspace it runs in
  const { type: _type, confirm: _confirm, ...fields } = action
  const job = await makeRealCharacter({ workspace: space, ...fields })
  const done = job.status === 'completed' && job.result
  const message = i18n.t(done ? 'wizard:replies.realCharacterReady' : 'wizard:replies.realCharacterStarted',
    { name: action.name, jobId: job.jobId, file: job.result?.rigged_file ?? '' })
  return {
    message, metadata: job as unknown as Record<string, unknown>, jobId: job.jobId,
    target: { kind: 'output', id: done ? job.result!.rigged_file : job.jobId, title: action.name },
    ...(done ? { outputNames: [job.result!.rigged_file] } : {}),
  }
}

export function registerRealCharacterCapability(register: typeof defineCapability) {
  register<AgentMakeRealCharacterAction>({
    name: 'make_real_character',
    title: 'Make a realistic 3D person (PS2 style)',
    description: 'One realistic PS2-era 3D person made on the server as one job, model3d.real.make: Qwen paints the body from outfit_prompt (the clothes, in English) and the head from face_prompt (the face and hair, in English), the character is rigged on CPU and a photo face kit talks (only the mouth moves). gender man|woman; skin #rrggbb, height_m (metres), body, bottom (trousers|skirt|shorts) and seed are optional. A name already made keeps every field you leave out: to change only the clothes send name and outfit_prompt (only the body is repainted); to change the face send name and face_prompt (the head and the face kit are redone). It takes minutes of GPU; the person follows it, sees the warnings and remakes it in Studio 3D › Realista (PS2).',
    useWhen: 'The user asks for a realistic 3D person or character, a PS2 or video-game style realistic character, or to change the clothes or the face of one ("hazme un hombre realista con traje", "cámbiale la ropa a Marta").',
    parameters: ['name', 'gender', 'skin', 'height_m', 'body', 'bottom', 'outfit_prompt', 'face_prompt', 'seed', 'talk_kit', 'confirm'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'make_real_character' }, name: { type: 'string', maxLength: 64 }, gender: { enum: GENDERS },
        skin: { type: 'string', description: '#rrggbb' }, height_m: { type: 'number', minimum: 1.2, maximum: 2.2, description: 'metres' }, body: { enum: BODIES }, bottom: { enum: BOTTOMS },
        outfit_prompt: { type: 'string', maxLength: 1200, description: 'the clothes and shoes, in English' },
        face_prompt: { type: 'string', maxLength: 1200, description: 'the face and hair (age, eyes, beard), in English' },
        seed: { type: 'integer', minimum: 0 }, talk_kit: { type: 'boolean' }, confirm: { const: true },
      },
      required: ['type', 'name', 'confirm'],
    },
    risk: 'compute', confirmation: 'required', progress: 'wizard:progress.makingRealCharacter',
    resolve(raw) { return resolveRealCharacter(raw) },
    validate(action) { return action.confirm === true ? [] : ['confirmation is required'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.realCharacter.make(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'output', successState: 'queued' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: '3d', anchors: ['real'], replay: 'atomic' },
  })
}
