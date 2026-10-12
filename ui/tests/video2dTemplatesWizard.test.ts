import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { runRegisteredCapability } from '../src/features/agent/capabilityRunner.ts'
import { video2dTemplateMessage } from '../src/features/agent/video2dTemplateCapabilities.ts'

const SUGGESTED = {
  version: 1, status: 'completed', operation: 'scenes.templates.suggest',
  result: {
    templates: [
      { id: 'music-pinball', titleEs: 'Rebote de pinball', titleEn: 'Pinball bounce', reason: 'one figure that bounces on the beat' },
      { id: 'music-trampoline', titleEs: 'Cama elástica', titleEn: 'Trampoline', reason: 'one figure that rises and falls' },
    ],
    unknown_words: ['zeppelin'],
  },
}

test('the Wizard asks scenes.templates.suggest through the 2D card route and shows the real cards', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('video2d_templates'), true)
  const capability = getCapability('video2d_templates')!
  assert.equal(capability.risk, 'read')
  assert.equal(capability.resolve({ type: 'video2d_templates', operation: 'scenes.template.compile', input: {} }), null)
  assert.equal(capability.resolve({ type: 'video2d_templates', operation: 'scenes.templates.suggest', input: [] }), null)
  const action = capability.resolve({ type: 'video2d_templates', operation: 'scenes.templates.suggest', input: { line: 'she bounces on the beat', speakers: 1 } })
  assert.deepEqual(action, { type: 'video2d_templates', operation: 'scenes.templates.suggest', input: { line: 'she bounces on the beat', speakers: 1 } })
  const sent: Array<{ url: string, body: Record<string, unknown> }> = []
  const previousFetch = globalThis.fetch
  globalThis.fetch = (async (url, init) => {
    sent.push({ url: String(url), body: JSON.parse(String(init?.body)) })
    return new Response(JSON.stringify(SUGGESTED), { status: 200 })
  }) as typeof fetch
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const outcome = await capability.execute(action!, { adapters: createDefaultApplicationAdapters(), workspace: 'show' })
    assert.deepEqual(sent, [{ url: '/api/v1/scenes/templates/commands', body: {
      operation: 'scenes.templates.suggest', version: 1, input: { line: 'she bounces on the beat', speakers: 1 } } }])
    assert.match(outcome.message, /^music-pinball \| Rebote de pinball \| Pinball bounce \| one figure that bounces on the beat$/m)
    assert.match(outcome.message, /music-trampoline/)
    assert.match(outcome.message, /Ninguna carta conoce: zeppelin/)
    assert.deepEqual(outcome.target, { kind: 'video_2d_template', id: 'music-pinball', title: 'scenes.templates.suggest' })
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('a read-only card search leaves no Wizard change trail and a refusal keeps its message', async () => {
  const previousFetch = globalThis.fetch
  const urls: string[] = []
  globalThis.fetch = (async url => {
    urls.push(String(url))
    return new Response(JSON.stringify(SUGGESTED), { status: 200 })
  }) as typeof fetch
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const result = await runRegisteredCapability({ type: 'video2d_templates', operation: 'scenes.catalog', input: { kind: 'templates', q: 'rebote' } }, {
      adapters: createDefaultApplicationAdapters(), workspace: 'show',
      availability: { location: { tab: 'images' }, labs: {
        story: { project_id: '' }, series: { series_id: '', episode_id: '', shots: 0, approved: 0 },
      } },
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    assert.equal(result?.report?.state, 'completed')
    assert.deepEqual(urls, ['/api/v1/scenes/templates/commands'])
    globalThis.fetch = (async () => new Response(JSON.stringify({ detail: { code: 'catalog_bad_envelope', message: 'Expected version 1' } }), { status: 422 })) as typeof fetch
    const { executeVideo2DTemplates } = await import('../src/features/agent/video2dTemplateCapabilities.ts')
    await assert.rejects(executeVideo2DTemplates({ type: 'video2d_templates', operation: 'scenes.catalog', input: {} }), /Expected version 1/)
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('catalog pages and one card read as lines, and the Wizard knows how to write a scene2d shot', () => {
  assert.equal(video2dTemplateMessage({ result: { kind: 'templates', entries: [
    { id: 'music-pinball', name: 'Rebote de pinball', description: 'El foco rebota.' }] } }), 'music-pinball | Rebote de pinball | El foco rebota.')
  assert.equal(video2dTemplateMessage({ result: { entry: { id: 'music-orbit', title: 'Órbita musical' } } }), 'music-orbit | Órbita musical')
  assert.equal(video2dTemplateMessage({ result: { templates: [] } }), 'Ninguna carta 2D coincide.')
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /video2d_templates/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /"kind": "scene2d"/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /Only music-\* cards play in production/)
  assert.doesNotMatch(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /scenes\.catalog and particle rain are not these shots/)
})
