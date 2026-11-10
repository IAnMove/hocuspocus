import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA, parseAgentTurn } from '../src/features/agent/agentActions.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { projectWizardContextCapabilities } from '../src/features/agent/wizardCapabilityAvailability.ts'
import { WORLD3D_PLAN_OPERATION, planInput, world3dPlanMessage } from '../src/features/agent/world3dTemplatePlanCapability.ts'
import { WORLD3D_TEMPLATE_OPERATIONS, world3dTemplateCommandIntent, world3dTemplateMessage } from '../src/features/agent/world3dTemplateCapabilities.ts'

const REPLY = {
  status: 'completed',
  result: {
    plan: [
      { key: 's1', primary: { id: 'stage-cocina', title: 'Kitchen', shot: 'wide', why: 'stage cocina, two_shot camera: wide, 2 subjects', scene3d: { template: 'stage-cocina', roomCamera: 'two_shot' } },
        alternates: [], warnings: [] },
      { key: 's2', primary: { id: 'cine-ratio-switch', title: 'Ratio switch', shot: 'close', why: 'one subject, close (landscape card, reframed)', adapted: true, scene3d: { template: 'cine-ratio-switch' } },
        alternates: [], warnings: ['adapted: landscape card in a portrait frame'] },
      { key: 's3', primary: null, alternates: [], warnings: ['no_card: no card fits this shot with the other choices'] },
    ],
    summary: { templates_used: 2, repeats: 0, formats: { landscape: 2 } },
  },
}

test('plan_3d_templates is a registered read-only Wizard action with the MCP tool\'s fields', () => {
  assert.equal(AGENT_ACTION_TYPES.includes('plan_3d_templates'), true)
  const capability = getCapability('plan_3d_templates')!
  assert.equal(capability.risk, 'read')
  assert.equal(capability.confirmation, 'none')
  assert.equal(capability.presentation.destination, 'action')
  assert.equal(capability.report.targetKind, 'video_3d_scene')
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } })
    .properties.actions.items.properties
  for (const key of ['shots', 'format', 'avoid', 'per_shot', 'seed']) assert.ok(properties[key], key)
  const parsed = parseAgentTurn(JSON.stringify({ reply: 'Hecho.', actions: [{ type: 'plan_3d_templates', shots: [{ key: 's1', text: 'dos amigos discuten en una cocina', speakers: 2 }] }] }))
  assert.equal(parsed.actions[0]?.type, 'plan_3d_templates')
  assert.equal(WORLD3D_TEMPLATE_OPERATIONS.includes(WORLD3D_PLAN_OPERATION as never), false, 'one door in the Wizard: world3d_templates does not take the plan')
  assert.equal(getCapability('world3d_templates')!.resolve({ type: 'world3d_templates', operation: WORLD3D_PLAN_OPERATION, input: { shots: [] } }), null)
})

test('the knowledge tells the planner to call the plan once for all the shots', () => {
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /plan_3d_templates ONCE for all the shots of a video/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /instead of one world3d_templates search per shot/)
})

test('the model\'s fields are cleaned and a plan needs at least one shot with its own key', () => {
  const plan = getCapability('plan_3d_templates')!
  assert.equal(plan.resolve({ type: 'plan_3d_templates', shots: [] }), null)
  assert.equal(plan.resolve({ type: 'plan_3d_templates', shots: 'two friends' }), null)
  assert.equal(plan.resolve({ type: 'plan_3d_templates', shots: [null, 3, []] }), null)
  const action = plan.resolve({
    type: 'plan_3d_templates', format: 'portrait', per_shot: 2, seed: 7, avoid: ['two-shot', '', 5],
    shots: [{ key: 'a', text: '  dos amigos en la cocina ', speakers: 2, subjects: 9, place: '', shot: 'huge', moving: 'yes' },
            { text: 'primer plano', speakers: 0, shot: 'close', moving: true, place: 'azotea' }],
  })
  assert.deepEqual(action, {
    type: 'plan_3d_templates', format: 'portrait', perShot: 2, seed: 7, avoid: ['two-shot'],
    shots: [{ key: 'a', text: 'dos amigos en la cocina', speakers: 2 }, { key: 's2', text: 'primer plano', speakers: 0, place: 'azotea', shot: 'close', moving: true }],
  })
  assert.deepEqual(planInput(action as never), {
    shots: (action as { shots: unknown }).shots, format: 'portrait', avoid: ['two-shot'], per_shot: 2, seed: 7,
  })
  assert.deepEqual(plan.validate(action as never), [])
  const twice = plan.resolve({ type: 'plan_3d_templates', shots: [{ key: 'a' }, { key: 'a' }] })!
  assert.equal(plan.validate(twice as never).length, 1)
})

test('the Wizard asks the plan through the template adapter once and lists key | id | title | shot | why', async () => {
  const plan = getCapability('plan_3d_templates')!
  const action = plan.resolve({ type: 'plan_3d_templates', shots: [{ key: 's1', text: 'cocina', speakers: 2 }, { key: 's2', text: 'ella contesta', speakers: 1 }], seed: 3 })!
  const seen: Array<{ operation: string, input: Record<string, unknown>, workspace: string | undefined }> = []
  const outcome = await plan.execute(action as never, {
    workspace: 'studio',
    adapters: { world3dTemplates: { command: async (got: { operation: string, input: Record<string, unknown> }, workspace?: string) => {
      seen.push({ operation: got.operation, input: got.input, workspace })
      return { message: world3dTemplateMessage(REPLY), target: { kind: 'video_3d_scene', id: 'world3d', title: got.operation } }
    } } },
  } as never)
  assert.equal(seen.length, 1)
  assert.equal(seen[0].operation, 'world3d.templates.plan')
  assert.equal(seen[0].workspace, 'studio')
  assert.deepEqual(Object.keys(seen[0].input), ['shots', 'seed'])
  assert.equal('intent_id' in seen[0].input, false)
  assert.equal(world3dTemplateCommandIntent(seen[0].operation, seen[0].input), undefined, 'read-only: no intent id')
  const lines = outcome.message.split('\n')
  assert.match(lines[0], /3 shots/)
  assert.equal(lines[1], 's1 | stage-cocina | Kitchen | wide | stage cocina, two_shot camera: wide, 2 subjects')
  assert.equal(lines[2], 's2 | cine-ratio-switch | Ratio switch | close | one subject, close (landscape card, reframed)')
  assert.equal(lines[3], 's3 | -')
  assert.ok(lines.some(line => line === 's2: adapted: landscape card in a portrait frame'))
  assert.ok(lines.some(line => line.startsWith('s3: no_card')))
  assert.equal(lines.at(-1), '2 different cards, 0 repeated.')
  assert.equal(plan.summarize(action as never, outcome as never), outcome.message)
})

test('the plan reply is shown by the same message function as every other template reply', () => {
  assert.equal(world3dTemplateMessage(REPLY), world3dPlanMessage(REPLY.result))
  assert.match(world3dTemplateMessage(REPLY), /s1 \| stage-cocina/)
  assert.doesNotMatch(world3dTemplateMessage(REPLY), /undefined|Video 3D ready/)
  assert.match(world3dPlanMessage({}), /0 shots/)
})

test('the plan works wherever the user is: it needs no tab, series or episode', () => {
  const context = (tab: string) => ({ location: { tab }, labs: { story: { project_id: '' }, series: { series_id: '', episode_id: '', shots: 0, approved: 0 } } })
  for (const tab of ['series_lab', 'productions', 'video_3d']) {
    const found = projectWizardContextCapabilities(context(tab) as never)
    assert.ok(found.available.includes('plan_3d_templates'), tab)
    assert.equal(found.blocked.some(entry => entry.name === 'plan_3d_templates'), false)
  }
})
