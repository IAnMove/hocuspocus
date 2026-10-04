import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createLipsPack } from '../src/lib/lipsCreator'
import type { CharacterKitLibrary } from '../src/lib/characterKit'
import type { ModelDef } from '../src/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  sessionStorage: dom.window.sessionStorage, HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = () => ({ matches: false }) as MediaQueryList
const originalFetch = globalThis.fetch
const model = { model_type: 'qwen_image_21', architecture: 'qwen_image_21', name: 'Qwen', family: 'qwen', is_downloaded: true, supports_ref_images: true } as ModelDef

test.after(() => { globalThis.fetch = originalFetch })

async function flow(failure: 'save' | 'terminal' | 'submission' | undefined = undefined) {
  const { useStore } = await import('../src/stores/useStore')
  useStore.setState({ activeWorkspace: 'wizard-mouths', models: [model], loadOutputs: async () => {} })
  const pack = createLipsPack('Wizard Ruby'); pack.lookNotes = 'Red ink lips'; pack.mouthGenerationMode = 'description'
  let library: CharacterKitLibrary = { version: 1, revision: 4, activeId: pack.id, kits: { [pack.id]: pack } }
  const submissions: Record<string, unknown>[] = [], captures: Record<string, unknown>[] = []
  globalThis.createImageBitmap = async () => ({ width: 2, height: 1, close() {} }) as ImageBitmap
  dom.window.HTMLCanvasElement.prototype.getContext = (() => ({ drawImage() {}, getImageData() { return { data: new Uint8ClampedArray([0, 0, 0, 0, 255, 0, 0, 255]) } } })) as never
  globalThis.fetch = async (input, init) => {
    const path = String(input)
    const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    if (path.includes('/lips-creator/library?')) return reply(library)
    if (path.includes('/defaults/')) return reply({ resolution: '512x512', num_inference_steps: 4, seed: -1, guidance_scale: 1 })
    if (path.endsWith('/generate')) {
      const body = JSON.parse(String(init?.body))
      // Each successful result must be committed before the next generation admission.
      assert.equal(captures.length, submissions.length)
      submissions.push(body)
      if (failure === 'submission') return reply({ detail: 'Unavailable' }, 503)
      return reply({ job_id: `job-${submissions.length}`, status: 'queued' })
    }
    if (path.includes('/status/')) {
      const firstFailed = failure === 'terminal' && path.endsWith('job-1')
      if (firstFailed) captures.push({ failed: true }) // records terminal completion for the sequencing assertion
      return reply({ job_id: path.split('/').pop(), status: firstFailed ? 'failed' : 'completed', error: firstFailed ? 'Image failed' : undefined, output_files: firstFailed ? [] : ['mouth.png'] })
    }
    if (path.includes('/lips-creator/commands')) {
      const command = JSON.parse(String(init?.body))
      assert.equal(command.input.workspace, 'wizard-mouths'); assert.equal(command.operation, 'lips.capture')
      assert.equal(command.input.base_revision, library.revision)
      if (failure === 'save') return reply({ detail: 'Revision conflict' }, 409)
      captures.push(command.input)
      library = { ...library, revision: library.revision + 1, kits: { [pack.id]: { ...library.kits[pack.id], mouthCandidates: { ...library.kits[pack.id].mouthCandidates, [command.input.state]: command.input.asset } } } }
      return reply({ version: 1, status: 'completed', result: { pack_id: pack.id, library } })
    }
    if (path.includes('/file/')) return new Response(new Blob(['test mouth']))
    throw new Error(`Unexpected request: ${path}`)
  }
  return { pack, submissions, captures, library: () => library }
}

test('Wizard publishes Lips Creator navigation and typed commands, validates states and executes through adapters', async () => {
  const { getCapability } = await import('../src/features/agent/capabilityRegistry')
  const command = getCapability('lips_creator')!, generation = getCapability('generate_lips')!
  assert.equal(generation.resolve({ type: 'generate_lips', pack_id: 'ruby', states: ['invalid'], confirm: true }), null)
  assert.equal(generation.resolve({ type: 'generate_lips', pack_id: 'ruby', states: ['bite', 'bite'], confirm: true }), null)
  assert.equal(generation.resolve({ type: 'generate_lips', pack_id: 'ruby' }), null)
  const action = command.resolve({ type: 'lips_creator', operation: 'list', input: {} })!
  let called = false
  await command.execute(action, { workspace: 'exact-workspace', adapters: { lipsCreator: { command: async (_action: unknown, workspace: string) => { called = true; assert.equal(workspace, 'exact-workspace'); return { message: 'listed' } } } } as never })
  assert.equal(called, true)
  assert.deepEqual(getCapability('open_tab')!.resolve({ type: 'open_tab', tab: 'lips_creator' }), { type: 'open_tab', tab: 'lips_creator' })
})

test('Wizard generates selected mouths sequentially and persists pending candidates before advancing', async () => {
  const fixture = await flow()
  const { generateLipsCollection } = await import('../src/features/characters/lipsActions')
  const result = await generateLipsCollection({ packId: fixture.pack.id, model: '', states: ['wide', 'bite'] }, 'wizard-mouths')
  assert.equal(fixture.submissions.length, 2); assert.equal(fixture.captures.length, 2)
  assert.deepEqual(fixture.captures.map(item => item.state), ['wide', 'bite'])
  for (const request of fixture.submissions) {
    assert.equal(request.workspace, 'wizard-mouths'); assert.equal(request.model_type, 'qwen_image_21')
    assert.equal(request.resolution, '1024x1024'); assert.match(String(request.prompt), /Red ink lips.*entirely from the description/)
    assert.equal(request.image_start, undefined)
  }
  assert.equal(result.metadata.completed, 2)
  assert.equal(fixture.library().revision, 6)
  assert.deepEqual(fixture.library().kits[fixture.pack.id].mouth, {})
  assert.equal(fixture.library().kits[fixture.pack.id].mouthCandidates!.bite!.reviewState, 'pending')
})

test('Wizard stops after a save failure or uncertain admission and never submits the next mouth', async () => {
  const { generateLipsCollection } = await import('../src/features/characters/lipsActions')
  for (const failure of ['save', 'submission'] as const) {
    const fixture = await flow(failure)
    await assert.rejects(generateLipsCollection({ packId: fixture.pack.id, model: '', states: ['wide', 'bite'] }, 'wizard-mouths'), /Revision conflict|Unavailable/)
    assert.equal(fixture.submissions.length, 1); assert.equal(fixture.library().revision, 4)
  }
})

test('Wizard continues only after confirmed failed jobs and reports partial results', async () => {
  const fixture = await flow('terminal')
  const { generateLipsCollection } = await import('../src/features/characters/lipsActions')
  const result = await generateLipsCollection({ packId: fixture.pack.id, model: '', states: ['wide', 'bite'] }, 'wizard-mouths')
  assert.equal(fixture.submissions.length, 2)
  assert.equal(result.metadata.completed, 1); assert.equal(result.report?.state, 'partial')
  assert.equal(fixture.library().kits[fixture.pack.id].mouthCandidates!.bite!.reviewState, 'pending')
})
