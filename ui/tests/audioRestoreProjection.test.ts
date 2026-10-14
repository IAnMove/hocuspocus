// Load Settings / reroll / pencil+Generate on a Speech, Music or SFX output must reach the
// closed generation.* command builders. Restore used to write video/H3 "inactive" sentinels
// (minimax_h3_extended_duration=false, frames_positions='', ...) that the Speech and Music
// projections refuse, so every audio reroll failed client side without posting anything.
import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent,
  MutationObserver: dom.window.MutationObserver })
window.matchMedia = (() => ({ matches: false })) as typeof window.matchMedia
const { useStore } = await import('../src/stores/useStore')
const { projectStudioSpeechFormParams, createStudioSpeechGenerationCommand } = await import('../src/features/studio/speechGenerationSpec')
const { projectStudioMusicFormParams, createStudioMusicGenerationCommand } = await import('../src/features/studio/musicGenerationSpec')
const { projectStudioSfxFormParams, createStudioSfxGenerationCommand } = await import('../src/features/studio/sfxGenerationSpec')
const { applyStudioAudioSubmitParams } = await import('../src/stores/studioAudioSubmit')
const { neutralizeSfxOwnedFormFields } = await import('../src/features/studio/sfxFormResidue')

type Call = { url: string; method: string; body: string }

const SPEECH = { model_type: 'kugelaudio_0_open', _audio_sub_mode: 'speech', generation_mode: 'audio',
  prompt: 'Speaker 1: Hello there.', _tts_original_prompt: 'Tentri: Hello there.',
  _tts_voice_count: 1, _tts_speaker_name1: 'Tentri', duration_seconds: 12, num_inference_steps: 0, guidance_scale: 3, seed: 7 }
const MUSIC = { model_type: 'ace_step_v1_5_xl_sft_lm_4b', _audio_sub_mode: 'music', generation_mode: 'audio',
  prompt: '[Verse]\nla la', alt_prompt: 'synth pop', duration_seconds: 20, num_inference_steps: 8, guidance_scale: 1, seed: 7 }
const SFX = { model_type: 'mmaudio_v2', _audio_sub_mode: 'sfx', sfx_mode: true, generation_mode: 'audio',
  prompt: 'a glass chime', MMAudio_prompt: 'a glass chime', duration_seconds: 3, num_inference_steps: 25 }

async function withAudio(sidecar: Record<string, unknown>, run: (calls: Call[]) => Promise<void>) {
  const before = useStore.getState(), beforeFetch = globalThis.fetch
  const calls: Call[] = []
  try {
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input), method = init?.method || 'GET'
      calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : '' })
      // Reject the real submission so no status poll starts; the test only needs to know it was sent.
      if (method !== 'GET' && /generation\/commands|\/api\/v1\/generate\b/.test(url)) {
        throw new Error('stub: submission reached the network')
      }
      return new Response('{}', { headers: { 'content-type': 'application/json' } })
    }) as typeof fetch
    useStore.setState({ generationMode: 'audio', audioSubMode: 'speech', activeWorkspace: 'audio-restore',
      audioReferenceStash: {}, selectedModelPerAudioSubMode: {}, jobs: [],
      models: [
        { model_type: 'kugelaudio_0_open', name: 'Kugel', family: 'tts', is_downloaded: true },
        { model_type: 'ace_step_v1_5_xl_sft_lm_4b', name: 'ACE', family: 'tts', is_downloaded: true },
        { model_type: 'mmaudio_v2', name: 'MMAudio', family: 'tts', is_downloaded: true },
      ] as typeof before.models,
      selectedOutputMeta: { params: sidecar } as never,
      loadModelOptions: async () => {}, loadLoras: async () => {} })
    await run(calls)
  } finally {
    await new Promise(resolve => setTimeout(resolve, 20))
    useStore.setState(before); globalThis.fetch = beforeFetch
  }
}

/** The form after Load Settings, with the same transforms the Speech/Music/SFX submissions apply before the closed projection. */
async function restoredAudioForm(sidecar: Record<string, unknown>) {
  let form: Record<string, unknown> = {}
  await withAudio(sidecar, async () => {
    assert.equal(await useStore.getState().loadSettingsFromOutput(), true)
    const state = useStore.getState()
    const full = JSON.parse(JSON.stringify(applyStudioAudioSubmitParams(
      { ...state.params, generation_mode: 'audio', workspace: 'audio-restore' }, state)))
    form = sidecar._audio_sub_mode === 'sfx' ? full : neutralizeSfxOwnedFormFields(full)   // SFX keeps its own fields
  })
  return form
}

test('Speech Load Settings leaves no field the closed generation.speech builder refuses', async () => {
  const projected = projectStudioSpeechFormParams(await restoredAudioForm(SPEECH)).params
  assert.doesNotThrow(() => createStudioSpeechGenerationCommand(projected, 'audio-restore-speech'))
})

test('Music Load Settings leaves no field the closed generation.music builder refuses', async () => {
  const projected = projectStudioMusicFormParams(await restoredAudioForm(MUSIC)).params
  assert.doesNotThrow(() => createStudioMusicGenerationCommand(projected, 'audio-restore-music'))
})

test('an audio restore clears the video and H3 residue instead of writing inactive sentinels', async () => {
  for (const sidecar of [SPEECH, MUSIC, SFX]) {
    await withAudio(sidecar, async () => {
      await useStore.getState().loadSettingsFromOutput()
      const params = useStore.getState().params as Record<string, unknown>
      for (const key of ['minimax_h3_extended_duration', 'minimax_h3_planning_style', 'minimax_h3_audio_policy',
        'minimax_h3_semantic_bridge_alpha', 'minimax_h3_semantic_bridge_magnitude',
        'frames_positions', 'image_start', 'image_end']) {
        assert.equal(params[key], undefined, `${sidecar._audio_sub_mode}: ${key} = ${JSON.stringify(params[key])}`)
      }
      assert.equal(params.model_type, sidecar.model_type)
      assert.equal(params.prompt, sidecar._tts_original_prompt ?? sidecar.prompt)
    })
  }
})

test('SFX Load Settings still projects cleanly through the closed generation.sfx builder', async () => {
  const projected = projectStudioSfxFormParams(await restoredAudioForm(SFX))
  assert.doesNotThrow(() => createStudioSfxGenerationCommand(projected, 'audio-restore-sfx'))
})

/** Stands in for the mounted Speech/Music panel that acknowledges the command before it is posted. */
function mountAudioPanel(subMode: 'speech' | 'music') {
  const panel = document.createElement('div')
  panel.setAttribute(`data-studio-${subMode}-ready`, 'true')
  panel.setAttribute(`data-studio-${subMode}-listening`, 'true')
  document.body.appendChild(panel)
  const event = `hocuspocus:studio-${subMode}-presentation`
  const onPresent = (e: Event) => {
    const request = (e as CustomEvent).detail as { command: { intent_id: string }; respond: () => void }
    panel.setAttribute(`data-studio-${subMode}-command`, request.command.intent_id)
    request.respond()
  }
  window.addEventListener(event, onPresent)
  return () => { window.removeEventListener(event, onPresent); panel.remove() }
}

// SFX is left out of the reroll loop: its closed builder was never affected (covered by the projection test above).
for (const [label, subMode, sidecar] of [['Speech', 'speech', SPEECH], ['Music', 'music', MUSIC]] as const) {
  test(`${label}: reroll reaches the submission`, async () => {
    const unmount = mountAudioPanel(subMode)
    try {
      await withAudio(sidecar, async calls => {
        await useStore.getState().rerollGeneration()
        const posts = calls.filter(c => c.method !== 'GET' && /generation\/commands|\/generate\b/.test(c.url))
        assert.equal(posts.length > 0, true, `no submission; job error: ${useStore.getState().jobs[0]?.error}`)
      })
    } finally { unmount() }
  })
}
