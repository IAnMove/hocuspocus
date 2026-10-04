import type { defineCapability } from './capabilityRegistry'
import { CHARACTER_MOUTH_STATES, type CharacterMouthState } from '../../lib/characterMouthStates'
import type { AgentLipsCreatorAction, AgentGenerateLipsAction } from './characterKitActions'
import { LIPS_OPERATIONS } from '../characters/lipsCommands'

const id = { type: 'string', pattern: '^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$' }
const stateList = { type: 'array', minItems: 1, maxItems: 9, uniqueItems: true, items: { enum: [...CHARACTER_MOUTH_STATES] } }
const operations = new Set<string>(LIPS_OPERATIONS)
const registrars = new WeakSet<object>()
export function registerLipsCreatorCapabilities(register: typeof defineCapability) {
  if (registrars.has(register)) return
  registrars.add(register)
  register<AgentLipsCreatorAction>({
    name: 'lips_creator', title: 'Manage Lips Creator',
    description: 'List, create, edit, review or link workspace mouth collections through the same command service as MCP. Use exact IDs and revisions. Capture never approves a generated mouth. Accept only after explicit approval of reviewed images.',
    useWhen: 'The user asks to manage reusable mouth collections, assign vowels or apply mouths to a character.', parameters: ['operation', 'input'],
    inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'lips_creator' }, operation: { enum: LIPS_OPERATIONS },
      input: { type: 'object', additionalProperties: false, properties: { name: { type: 'string' }, description: { type: 'string' }, style: { enum: ['cutout', 'children-illustration', 'anime-2d'] },
        pack_id: id, character_id: id, pose_id: id, base_revision: { type: 'integer', minimum: 0 }, changes: { type: 'object' }, reference: { type: 'object' }, asset: { type: 'object' },
        state: { enum: CHARACTER_MOUTH_STATES }, states: stateList } } }, required: ['type', 'operation', 'input'] },
    risk: 'edit', confirmation: 'none', progress: 'Actualizando Lips Creator…',
    resolve(raw) {
      return typeof raw.operation === 'string' && operations.has(raw.operation) && raw.input && typeof raw.input === 'object' && !Array.isArray(raw.input)
        ? { type: 'lips_creator', operation: raw.operation as AgentLipsCreatorAction['operation'], input: raw.input as Record<string, unknown> } : null
    },
    validate(action) { return operations.has(action.operation) ? [] : ['Choose a Lips Creator operation.'] },
    async prepare(action) { return action }, async execute(action, context) { return context.adapters.lipsCreator.command(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
    report: { targetKind: 'lips_creator', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'lips_creator', anchors: ['collection'], replay: 'atomic' },
  })
  register<AgentGenerateLipsAction>({
    name: 'generate_lips', title: 'Generate Lips Creator mouths', description: 'Generate missing mouths sequentially, saving every output as a candidate before the next job. Pass states to regenerate only those mouths. Keeps approved drawings intact. Stops on uncertain job or save errors.',
    useWhen: 'The user explicitly asks to generate or regenerate mouths in a saved collection.', parameters: ['pack_id', 'states', 'model', 'confirm'],
    inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'generate_lips' }, pack_id: id, states: stateList, model: { type: 'string' }, confirm: { const: true } }, required: ['type', 'pack_id', 'confirm'] },
    risk: 'compute', confirmation: 'required', progress: 'Generando bocas de Lips Creator…',
    resolve(raw) {
      if (raw.confirm !== true || typeof raw.pack_id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(raw.pack_id)) return null
      if (raw.states !== undefined && (!Array.isArray(raw.states) || !raw.states.length || raw.states.length > 9 || new Set(raw.states).size !== raw.states.length || raw.states.some(state => !CHARACTER_MOUTH_STATES.includes(state as CharacterMouthState)))) return null
      return { type: 'generate_lips', packId: raw.pack_id, states: raw.states as CharacterMouthState[] | undefined, model: typeof raw.model === 'string' ? raw.model : '', confirm: true }
    },
    validate(action) { return action.packId && action.confirm === true ? [] : ['Use an exact pack ID and explicit generation request.'] },
    async prepare(action) { return action }, async execute(action, context) { return context.adapters.lipsCreator.generate(action, context.workspace, { onStep: context.onStep, generationContext: context.generationContext }) },
    correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
    report: { targetKind: 'lips_creator', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'lips_creator', anchors: ['mouths'], replay: 'atomic' },
  })
}
