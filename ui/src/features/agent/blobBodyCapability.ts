import type { defineCapability } from './capabilityRegistry'
import type { AgentBlobMakeAction } from './agentActions'

const BUILDS = ['slim', 'average', 'round', 'pear']
const HANDS = ['ball', 'mitten']
const FEET = ['shoe', 'ball', 'boot']
const FAMILIES = ['blob', 'anime', 'chibi']
const HAIR = ['none', 'short', 'bangs', 'spiky', 'long', 'ponytail', 'twin_tails', 'bun']
const PRESET_NAMES = [
  'sailor', 'cashier', 'boss', 'kid', 'big', 'lanky',
  'blob_chef', 'blob_pirate', 'blob_scout',
  'anime_girl', 'anime_boy', 'anime_senpai',
  'chibi_kid', 'chibi_mage', 'chibi_knight',
]

function text(value: unknown, max: number): string {
  return typeof value === 'string' ? value.trim().slice(0, max) : ''
}

function numberIn(value: unknown, min: number, max: number, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) return fallback
  return parsed
}

function choice(value: unknown, allowed: string[], fallback: string): string {
  return typeof value === 'string' && allowed.includes(value) ? value : fallback
}

export function registerBlobBodyCapability(register: typeof defineCapability) {
  register<AgentBlobMakeAction>({
    name: 'blob_make',
    title: 'Build a round-headed 3D person',
    description: 'Build one round-headed person from a preset or from traits and rig it on CPU in the same call as model3d.blob.make. Families are blob, anime and chibi. The face is not part of this body. The rigged GLB opens in the 3D gallery.',
    useWhen: 'The user asks for a round-headed 3D character, a blob, anime or chibi body, or one of the named presets.',
    parameters: ['name', 'preset', 'height', 'build', 'family', 'hair_style', 'head_width', 'hands', 'feet'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'blob_make' },
        name: { type: 'string', maxLength: 64 },
        preset: { enum: ['', ...PRESET_NAMES] },
        height: { type: 'number', minimum: 1.2, maximum: 2.2 },
        build: { enum: BUILDS },
        family: { enum: FAMILIES },
        hair_style: { enum: HAIR },
        head_width: { type: 'number', minimum: 0.12, maximum: 0.46 },
        hands: { enum: HANDS },
        feet: { enum: FEET },
      },
      required: ['type'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Building the blob…',
    resolve(raw) {
      const preset = choice(raw.preset, PRESET_NAMES, '')
      const given = (key: string) => raw[key] !== undefined && raw[key] !== null && raw[key] !== ''
      const keep = (key: string) => !preset || given(key)
      return {
        type: 'blob_make',
        name: text(raw.name, 64) || 'Blob',
        preset,
        ...(keep('height') ? { height: numberIn(raw.height, 1.2, 2.2, 1.8) } : {}),
        ...(keep('build') ? { build: choice(raw.build, BUILDS, 'average') } : {}),
        ...(keep('family') ? { family: choice(raw.family, FAMILIES, 'blob') } : {}),
        ...(keep('hair_style') ? { hairStyle: choice(raw.hair_style, HAIR, 'none') } : {}),
        ...(keep('head_width') ? { headWidth: numberIn(raw.head_width, 0.12, 0.46, 0.31) } : {}),
        ...(keep('hands') ? { hands: choice(raw.hands, HANDS, 'ball') } : {}),
        ...(keep('feet') ? { feet: choice(raw.feet, FEET, 'shoe') } : {}),
      }
    },
    validate(action) { return action.name.trim() ? [] : ['name is required'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.blobBody.make(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'output', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: '3d', anchors: ['blob'], replay: 'atomic' },
  })
}
