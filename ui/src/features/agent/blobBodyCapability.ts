import type { defineCapability } from './capabilityRegistry'
import type { AgentBlobMakeAction } from './agentActions'

const BUILDS = ['slim', 'average', 'round', 'pear']
const HANDS = ['ball', 'mitten']
const FEET = ['shoe', 'ball']
const PRESET_NAMES = ['sailor', 'cashier', 'boss', 'kid', 'big', 'lanky']

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
    description: 'Build one round-headed person from a preset (sailor, cashier, boss, kid, big, lanky) or from traits and rig it on CPU in the same call as model3d.blob.make. The face is not part of this body. The rigged GLB opens in the 3D gallery.',
    useWhen: 'The user asks for a round-headed 3D character, a blob body, or one of the presets (sailor, cashier, boss, kid, big, lanky).',
    parameters: ['name', 'preset', 'height', 'build', 'head_width', 'hands', 'feet'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'blob_make' },
        name: { type: 'string', maxLength: 64 },
        preset: { enum: ['', ...PRESET_NAMES] },
        height: { type: 'number', minimum: 1.2, maximum: 2.2 },
        build: { enum: BUILDS },
        head_width: { type: 'number', minimum: 0.24, maximum: 0.38 },
        hands: { enum: HANDS },
        feet: { enum: FEET },
      },
      required: ['type'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Building the blob…',
    resolve(raw) {
      return {
        type: 'blob_make',
        name: text(raw.name, 64) || 'Blob',
        preset: choice(raw.preset, PRESET_NAMES, ''),
        height: numberIn(raw.height, 1.2, 2.2, 1.8),
        build: choice(raw.build, BUILDS, 'average'),
        headWidth: numberIn(raw.head_width, 0.24, 0.38, 0.31),
        hands: choice(raw.hands, HANDS, 'ball'),
        feet: choice(raw.feet, FEET, 'shoe'),
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
