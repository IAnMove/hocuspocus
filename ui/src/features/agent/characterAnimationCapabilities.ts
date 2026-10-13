import type { defineCapability } from './capabilityRegistry'
import i18n from '../../i18n'
import { fetchCharacterKitLibrary } from '../../api/characters'
import { startAnimationJob, type CustomAnimationRequest } from '../../api/characterAnimationJobs'
import { useStore } from '../../stores/useStore'
import { animationDef, customViews, MAX_CUSTOM_POSES, MAX_CUSTOM_TEXT } from '../../lib/characterAnimations'
import type { CharacterKit } from '../../lib/characterKit'

/**
 * "Hazle una cara de enfado a Heroína", "que Inés salude": one animation of a saved character, made by the same server job that the
 * Character Creator's Animaciones panel and the characters.animation.make MCP tool start (POST /api/v1/character-kits/animations/make).
 * Every pose is made from the character's own picture and the result waits for a person's review in the panel: the Wizard never
 * approves it. A job takes minutes, so the Wizard starts it and says where to follow it instead of waiting.
 */
export interface AgentMakeCharacterAnimationAction {
  type: 'make_character_animation'
  /** The character's name or id; empty means the only (or the active) one. */
  kitName: string
  animation: string
  custom?: CustomAnimationRequest
  pose?: string
  confirm: true
}

const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/
const text = (value: unknown, limit: number): string => typeof value === 'string' ? value.trim().slice(0, limit) : ''

function customOf(raw: unknown): CustomAnimationRequest | undefined | null {
  if (raw === undefined || raw === null) return undefined
  if (typeof raw !== 'object' || Array.isArray(raw)) return null
  const { title, view, poses } = raw as Record<string, unknown>
  // The model fills the fields it does not use with empty values: those name no custom animation.
  if (!text(title, 80) && !text(view, 20) && (!Array.isArray(poses) || !poses.some(pose => text(pose, 4)))) return undefined
  const words = Array.isArray(poses) ? poses.map(pose => text(pose, MAX_CUSTOM_TEXT)).filter(Boolean) : []
  const framing = (customViews as string[]).includes(String(view)) ? view as CustomAnimationRequest['view'] : undefined
  return text(title, 80) && framing && words.length >= 1 && words.length <= MAX_CUSTOM_POSES ? { title: text(title, 80), view: framing, poses: words } : null
}

/** The character the user named: by id or name, or the only one, or the active one. */
export function findAnimationKit(kits: Record<string, CharacterKit>, activeId: string | undefined, name: string): CharacterKit {
  const all = Object.values(kits)
  const wanted = name.trim().toLowerCase()
  const found = wanted ? all.find(kit => kit.id.toLowerCase() === wanted || kit.name.trim().toLowerCase() === wanted) : (all.length === 1 ? all[0] : kits[activeId ?? ''])
  if (found) return found
  const names = all.map(kit => kit.name).join(', ')
  throw new Error(wanted ? `There is no character called “${name}” in this workspace${names ? ` (there are: ${names})` : ''}.`
    : all.length ? `Say which character: ${names}.` : 'There is no saved character in this workspace: create one in Character Creator first.')
}

export async function executeMakeCharacterAnimation(action: AgentMakeCharacterAnimationAction, workspace?: string) {
  const space = workspace || useStore.getState().activeWorkspace
  const library = await fetchCharacterKitLibrary(space)
  const kit = findAnimationKit(library.kits, library.activeId, action.kitName)
  const job = await startAnimationJob({ workspace: space, kitId: kit.id, animation: action.animation,
    ...(action.pose ? { pose: action.pose } : {}), ...(action.custom ? { custom: action.custom } : {}) })
  const key = job.status === 'queued' ? 'wizard:replies.characterAnimationQueued' : 'wizard:replies.characterAnimationStarted'
  return {
    message: i18n.t(key, { name: kit.name, animation: job.title || action.animation, poses: job.takes.length, jobId: job.jobId }),
    metadata: job as unknown as Record<string, unknown>, jobId: job.jobId,
    target: { kind: 'character_kit', id: kit.id, title: kit.name },
  }
}

export function registerCharacterAnimationCapabilities(register: typeof defineCapability) {
  register<AgentMakeCharacterAnimationAction>({
    name: 'make_character_animation',
    title: 'Make an animation of a saved character',
    description: 'Make one small animation (a walk, a gesture such as waving, or an anime expression such as angry) of a saved Character Kit with its own picture as the identity reference, on the server: every pose with Qwen, keyed, joined into a sprite sheet and saved on the character as pending review. animation_id is an id of the animation catalog; for one the catalog does not list give a new lowercase slug and custom_animation {title, view bust|front|side, poses: one description per pose, up to six}. pose_id makes that one pose of an animation already made again. It takes minutes, one animation at a time; the person reviews and approves it in Character Creator › Animaciones (you never approve it).',
    useWhen: 'The user asks for an animation, gesture, expression or walk of a saved character ("hazle una cara de enfado a Heroína", "que salude", "una animación de andar", "una sonrisa pícara"), or to redo one pose of one.',
    parameters: ['kit_name', 'animation_id', 'custom_animation', 'pose_id', 'confirm'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'make_character_animation' }, kit_name: { type: 'string', maxLength: 160 }, animation_id: { type: 'string', maxLength: 64 },
        custom_animation: { type: 'object', additionalProperties: false, required: ['title', 'view', 'poses'], properties: {
          title: { type: 'string', maxLength: 80 }, view: { enum: [...customViews] },
          poses: { type: 'array', minItems: 1, maxItems: MAX_CUSTOM_POSES, items: { type: 'string', maxLength: MAX_CUSTOM_TEXT } } } },
        pose_id: { type: 'string', maxLength: 120 }, confirm: { const: true },
      },
      required: ['type', 'animation_id', 'confirm'],
    },
    risk: 'compute', confirmation: 'required', progress: 'wizard:progress.makingCharacterAnimation',
    resolve(raw) {
      const animation = text(raw.animation_id, 64).toLowerCase()
      const custom = customOf(raw.custom_animation)
      if (raw.confirm !== true || !SLUG.test(animation) || custom === null) return null
      return { type: 'make_character_animation', kitName: text(raw.kit_name, 160), animation, confirm: true,
               ...(custom ? { custom } : {}), ...(text(raw.pose_id, 120) ? { pose: text(raw.pose_id, 120) } : {}) }
    },
    validate(action) {
      if (action.confirm !== true) return ['confirmation is required']
      if (action.custom && animationDef(action.animation)) return [`${action.animation} is in the catalog: leave custom out`]
      return []
    },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.characterAnimations.make(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'character_kit', successState: 'queued' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'character_creator', anchors: ['animations'], replay: 'atomic' },
  })
}
