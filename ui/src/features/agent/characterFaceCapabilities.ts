import type { defineCapability } from './capabilityRegistry'
import i18n from '../../i18n'
import { BASE } from '../../api/http'

/** "Dibújale una cara de blob": the same CPU job as Characters › Crear cara and `characters.face.make`. */
export interface AgentMakeCharacterFaceAction {
  type: 'make_character_face'
  traits: Record<string, unknown>
  name?: string
}

export async function executeMakeCharacterFace(action: AgentMakeCharacterFaceAction, workspace?: string) {
  const space = workspace || 'default'
  const response = await fetch(`${BASE}/api/v1/character-kits/face`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace: space, traits: action.traits, ...(action.name ? { name: action.name } : {}) }),
  })
  const body = await response.json().catch(() => ({})) as { kit_id?: string; detail?: { message?: string } | string; character?: { name?: string } }
  if (!response.ok) {
    const detail = body.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || 'Could not draw the face')
  }
  const title = body.character?.name || action.name || body.kit_id || 'face'
  return {
    message: i18n.t('wizard:replies.characterFaceMade', { name: title }),
    metadata: body as Record<string, unknown>,
    target: { kind: 'character_kit' as const, id: body.kit_id || title, title },
  }
}

export function registerCharacterFaceCapabilities(register: typeof defineCapability) {
  register<AgentMakeCharacterFaceAction>({
    name: 'make_character_face',
    title: 'Draw a 2D blob face',
    description: 'Draw a parametric 2D face (blob style, or style anime with big shaded eyes, blush and small mouths: eyes, brows, nose, moustache, glasses, freckles, stubble) and save it as an approved Character Kit. Same route as Characters › Crear cara and characters.face.make. It is CPU work, not a GPU picture. traits uses eyes dot|oval|halflid|wide, brows thick|thin|none, nose none|dot|line|bulb, moustache none|walrus|pencil|handlebar, glasses none|round|square, mouth paper|ink, ink as #rrggbb. Bind the saved kit onto a model with world3d.scene.face.',
    useWhen: 'The user wants a drawn blob face, a moustache, glasses or freckles on a character, or a 2D face to put on a round 3D head.',
    parameters: ['name', 'traits'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'make_character_face' },
        name: { type: 'string', maxLength: 240 },
        traits: { type: 'object' },
      },
      required: ['type', 'traits'],
    },
    risk: 'edit', confirmation: 'none', progress: 'wizard:progress.makingCharacterFace',
    resolve(raw) {
      if (!raw.traits || typeof raw.traits !== 'object' || Array.isArray(raw.traits)) return null
      const name = typeof raw.name === 'string' ? raw.name.trim().slice(0, 240) : ''
      return { type: 'make_character_face', traits: raw.traits as Record<string, unknown>, ...(name ? { name } : {}) }
    },
    validate() { return [] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.characterFaces.make(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'character_kit', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'character_creator', anchors: ['library'], replay: 'atomic' },
  })
}
