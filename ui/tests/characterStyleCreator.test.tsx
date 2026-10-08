import assert from 'node:assert/strict'
import test, { type TestContext } from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { characterStyle, characterStyleLabel, characterStylePrompt, screenFor } from '../src/lib/characterStyles'
import { flaggedRigPoses } from '../src/lib/flatRigMouth'
import { generateKeyedCandidates, type KeyedCandidate } from '../src/features/characters/characterCandidates'
import { designVoiceCandidates, expectedPitch, referenceVoice, VOICE_DESIGN_MODEL } from '../src/features/characters/voiceDesign'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const style = characterStyle('paper-cutout')!

test('the paper cutout preset builds prompts on a screen the subject does not wear', () => {
  assert.equal(screenFor('Kevin in an orange hoodie'), 'green')
  assert.equal(screenFor('Ana con chaqueta verde'), 'magenta')
  const built = characterStylePrompt(style, 'pose', ' waving  hello ')
  assert.match(built.prompt, /same character as the reference image.*waving hello.*chroma-key green/s)
  assert.equal(built.screen, 'green')
})

test('three candidates are generated with distinct seeds and keyed as they arrive; a failure stays visible', async () => {
  const updates: KeyedCandidate[][] = [], keyed: unknown[] = []
  let seed = 10, call = 0
  const found = await generateKeyedCandidates({
    workspace: 'cast', style, kind: 'character', description: 'Lime robot', model: 'qwen_image_21',
    signal: new AbortController().signal, onUpdate: items => updates.push(items),
  }, {
    seed: () => seed++,
    generate: async (_provider, prompt, model, _ref, negative, options) => {
      call += 1
      assert.match(prompt, /Lime robot.*magenta/s)
      assert.equal(model, 'qwen_image_21'); assert.match(negative, /watermark/)
      assert.equal(options?.resolution, '896x1152')
      if (options?.seed === 11) throw new Error('out of memory')
      return { source: `/api/v1/file/raw-${options?.seed}.png?workspace=cast` } as never
    },
    key: async details => { keyed.push(details); return { file: 'k.png', url: `/api/v1/file/keyed-${String(details.source).slice(17, 23)}?workspace=cast`, sha256: 'x' } },
  })
  assert.equal(call, 3)
  assert.deepEqual(found.map(item => [item.seed, item.status]), [[10, 'ready'], [11, 'failed'], [12, 'ready']])
  assert.equal(found[1].error, 'out of memory')
  assert.ok(keyed.every(item => (item as { mode: string }).mode === 'magenta'))
  assert.ok(updates.some(items => items.some(item => item.status === 'keying')))
})

test('a candidate whose key left a haze says so', async () => {
  const found = await generateKeyedCandidates({
    workspace: 'cast', style, kind: 'character', description: 'Ines', model: 'qwen_image_21',
    signal: new AbortController().signal, onUpdate: () => {},
  }, {
    seed: () => 7,
    generate: async () => ({ source: '/api/v1/file/raw-7.png?workspace=cast' }) as never,
    key: async () => ({ file: 'k.png', url: '/api/v1/file/k.png?workspace=cast', sha256: 'x',
                        report: { semiTransparentShare: 0.42, transparentShare: 0.1, haze: true } }),
  })
  assert.ok(found.every(item => item.status === 'ready' && item.haze === 0.42))
})

test('voice design asks VoiceDesign three times, measures each take and keeps one as the reference', async () => {
  assert.deepEqual(expectedPitch('Male voice. Calm.'), [85, 155])
  assert.deepEqual(expectedPitch('Voz de mujer joven'), [165, 255])
  assert.deepEqual(expectedPitch('A small boy'), [220, 400])
  assert.deepEqual(expectedPitch('chica joven'), [165, 255])
  assert.equal(expectedPitch('A robot'), undefined)
  const submitted: Record<string, unknown>[] = [], checked: unknown[] = []
  let seed = 1
  const voices = await designVoiceCandidates({
    workspace: 'cast', description: 'Male voice. Low and slow.', text: 'Hola. Esta es mi voz.', language: 'spanish',
    signal: new AbortController().signal, onUpdate: () => {},
  }, {
    seed: () => seed++,
    submitGeneration: async params => { submitted.push(params); return { job_id: `job-${params.seed}` } as never },
    fetchJobStatus: async jobId => ({ status: 'completed', output_files: [`${jobId}.wav`] }) as never,
    checkSpeech: async details => { checked.push(details); return { transcript: 'Hola. Esta es mi voz.', wer: 0, medianPitchHz: 110, wordsPerSecond: 2.4, duration: 3, warnings: [] } },
    fileUrl: (name, workspace) => `/api/v1/file/${name}?workspace=${workspace}`,
  })
  assert.equal(submitted.length, 3)
  assert.deepEqual(submitted.map(params => params.seed), [1, 2, 3])
  assert.ok(submitted.every(params => params.model_type === VOICE_DESIGN_MODEL && params.alt_prompt === 'Male voice. Low and slow.'
    && params.model_mode === 'spanish' && params.prompt === 'Hola. Esta es mi voz.'))
  assert.deepEqual((checked[0] as { pitchRange: number[] }).pitchRange, [85, 155])
  assert.ok(voices.every(voice => voice.status === 'ready'))
  assert.deepEqual(referenceVoice(voices[0], { name: 'Kevin (spanish)', text: 'Hola. Esta es mi voz.', language: 'spanish' }), {
    provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference', name: 'Kevin (spanish)',
    referenceAudio: '/api/v1/file/job-1.wav?workspace=cast', transcript: 'Hola. Esta es mi voz.', language: 'spanish' })
})

type CreatorRequest = { method: string; url: string; body?: Record<string, unknown> }

/** The server a Character Creator run talks to: image jobs, keying, the kit library and the flat rig, whose reply
 * `rig` can extend (warnings, a provenance). */
function creatorServer(t: TestContext, rig: (kit: Record<string, unknown>) => Record<string, unknown> = () => ({})): CreatorRequest[] {
  const requests: CreatorRequest[] = []
  let job = 0
  const reply = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    requests.push({ method, url, body })
    if (url.includes('/api/v1/defaults/')) return reply({})
    if (url.includes('/api/v1/outputs')) return reply({ outputs: [], total: 0 })
    if (url.endsWith('/api/v1/generate')) return reply({ job_id: `img-${++job}` })
    if (url.includes('/api/v1/status/')) return reply({ status: 'completed', output_files: [`${url.split('/status/')[1]}.png`] })
    if (url.endsWith('/api/v1/studio/key')) return reply({ result: { file: 'k.png', url: `/api/v1/file/keyed-${String(body?.source).split('/').pop()}`, sha256: 'x' } })
    if (url.includes('/api/v1/character-kits/library?')) return reply({ version: 1, revision: 4, activeKitId: null, kits: {} })
    if (method === 'PATCH') return reply({ version: 1, revision: 5, kits: { [String((body?.kit as { id: string }).id)]: body?.kit } })
    if (url.endsWith('/flat-rig')) {
      const kit = requests.find(item => item.method === 'PATCH')!.body!.kit as Record<string, unknown>
      const extra = rig(kit)
      return reply({ revision: 6, review: '/api/v1/file/review.png?workspace=cast', unwipedPoses: [], poses: {}, ...extra,
        character: { ...kit, ...(extra.character as object | undefined) } })
    }
    return reply({})
  }) as typeof fetch
  return requests
}

/** Name and describe a character, create three options, pick the second and save it: the rig's review appears. */
async function createAndRig(creatorStyle: typeof style) {
  const { render, fireEvent, waitFor, screen } = await import('@testing-library/react')
  const { CharacterStyleCreator } = await import('../src/features/characters/CharacterStyleCreator')
  const view = render(<CharacterStyleCreator workspace="cast" style={creatorStyle} model="qwen_image_21" />)
  fireEvent.change(view.getByLabelText('Character name'), { target: { value: 'Kevin' } })
  fireEvent.change(view.getByLabelText('Character description'), { target: { value: 'Nervous founder, red hair' } })
  fireEvent.click(view.getByRole('button', { name: 'Create 3 options' }))
  const second = await waitFor(() => {
    const option = view.getByRole('button', { name: 'Option 2' }) as HTMLButtonElement
    assert.equal(option.disabled, false)
    return option
  }, { timeout: 8000 })
  fireEvent.click(second)
  fireEvent.click(view.getByRole('button', { name: 'Save and make it talk' }))
  await waitFor(() => assert.ok(screen.getByTestId('character-rig-review')), { timeout: 4000 })
  return view
}

test('description to a saved, rigged kit in the Character Creator', async t => {
  const { cleanup } = await import('@testing-library/react')
  t.after(cleanup)
  const requests = creatorServer(t)
  const view = await createAndRig(style)

  const saved = requests.find(item => item.method === 'PATCH')!.body!
  const kit = saved.kit as { base: { source: string; alphaStatus: string }; style: string }
  assert.equal(saved.baseRevision, 4)
  assert.match(kit.base.source, /^\/api\/v1\/file\/keyed-/)
  assert.equal(kit.base.alphaStatus, 'transparent')
  assert.equal(kit.style, 'cutout')
  const rig = requests.find(item => item.url.endsWith('/flat-rig'))!.body!
  assert.deepEqual(rig, { workspace: 'cast', baseRevision: 5, style: style.rig })
  assert.equal(requests.filter(item => item.url.endsWith('/api/v1/studio/key')).length, 3)
  assert.ok(view.getByTestId('character-new-pose'))
})

test('the graphic novel style is generated for the warp rig and rigged with warp mouths', () => {
  const painted = characterStyle('graphic-novel')!
  assert.deepEqual(painted.rig, { mouthStyle: 'warp' })
  for (const kind of ['character', 'pose'] as const) {
    const built = characterStylePrompt(painted, kind, 'Brother Anselmo')
    assert.match(built.prompt, /WHITE sclera.*closed mouth painted as one short dark line.*Brother Anselmo.*chroma-key green/s)
  }
  assert.deepEqual(flaggedRigPoses({ busto: ['mouth_line_guessed'], base: ['mouth_line_unsure', 'eyes_low'], wave: ['stray_mark'] }),
    { mouthLine: ['base', 'busto'], other: ['base', 'wave'] })
  assert.deepEqual(flaggedRigPoses(undefined), { mouthLine: [], other: [] })
})

test('the Wizard names the graphic novel style as the Character Creator shows it', async () => {
  const { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } = await import('../src/features/agent/agentKnowledge')
  assert.ok(HOCUSPOCUS_AGENT_SYSTEM_PROMPT.includes(`«${characterStyleLabel(characterStyle('graphic-novel')!, 'en')}»`))
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /warp mouths.*Prepare 2D speech › Mouth line/s)
})

test('a painted character is rigged with warp mouths and the poses whose mouth line needs a hand are named', async t => {
  const { cleanup } = await import('@testing-library/react')
  t.after(cleanup)
  const painted = characterStyle('graphic-novel')!
  const requests = creatorServer(t, kit => ({
    unwipedPoses: ['base'], warnings: { base: ['mouth_line_unsure'] },
    character: { provenance: [...(kit.provenance as object[]), { method: 'flat-rig', style: { mouthStyle: 'warp' } }] },
  }))
  const view = await createAndRig(painted)

  const kit = requests.find(item => item.method === 'PATCH')!.body!.kit as { provenance: { method: string; style: string }[] }
  assert.deepEqual(kit.provenance.map(entry => [entry.method, entry.style]), [['character-style-create', 'graphic-novel']],
    'the kit records its style, so a later rig with no style keeps warp mouths')
  assert.deepEqual(requests.find(item => item.url.endsWith('/flat-rig'))!.body!.style, { mouthStyle: 'warp' })
  assert.match(view.getByTestId('character-rig-mouth-line').textContent ?? '', /mouth line of base.*Prepare 2D speech.*Kevin.*Mouth line/)
  assert.match(view.getByTestId('character-rig-review').textContent ?? '', /the drawing's own/)
  assert.doesNotMatch(view.getByTestId('character-rig-review').textContent ?? '', /No painted mouth/, 'a warp mouth is placed by its line')
})

test('a language voice is designed in place, in that language', async t => {
  const { render, fireEvent, cleanup, within } = await import('@testing-library/react')
  const { CharacterLanguageVoices } = await import('../src/features/characters/CharacterLanguageVoices')
  t.after(cleanup)
  const view = render(<CharacterLanguageVoices workspace="cast" characterName="Kevin" onChange={() => {}}
    value={{ spanish: { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'ryan' } }} />)
  const block = within(view.getByTestId('language-voice-spanish'))
  fireEvent.click(block.getByRole('button', { name: 'Design a voice' }))
  const designer = within(view.getByTestId('character-voice-designer'))
  assert.equal((designer.getByLabelText('Language') as HTMLSelectElement).value, 'spanish')
  assert.match((designer.getByLabelText(/Sample line/) as HTMLTextAreaElement).value, /^Hola\./)
  assert.equal((designer.getByRole('button', { name: 'Create 3 voices' }) as HTMLButtonElement).disabled, true, 'a description is required')
})
