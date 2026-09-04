import assert from 'node:assert/strict'
import test from 'node:test'

async function registeredStudioCapabilities() {
  const { registerStudioCapabilities } = await import('../src/features/agent/studioCapabilities.ts')
  const definitions = []
  registerStudioCapabilities(definition => {
    definitions.push(definition)
    return definition
  })
  return new Map(definitions.map(definition => [definition.name, definition]))
}

test('registers the complete Studio family behind one injected registrar', async () => {
  const definitions = await registeredStudioCapabilities()
  assert.deepEqual([...definitions.keys()], [
    'prepare_video',
    'prepare_image',
    'prepare_audio',
    'prepare_3d',
    'queue_sfx_pack',
    'start_generation',
    'attach_studio_references',
    'configure_studio_loras',
    'download_model',
  ])
  assert.equal(definitions.get('prepare_video').presentation.destination, 'studio')
  assert.equal(definitions.get('prepare_video').report.successState, 'prepared')
  assert.equal(definitions.get('queue_sfx_pack').confirmation, 'required')
})
test('resolves Studio forms with bounded, canonical camelCase actions', async () => {
  const definitions = await registeredStudioCapabilities()

  const video = definitions.get('prepare_video').resolve({
    type: 'prepare_video',
    prompt: '  un castillo flotante  ',
    model_type: 'video-model',
    duration_seconds: 7.5,
    resolution_preset: '720p',
    aspect_ratio: '16:9',
    resolution: '1280x720',
    seed: 42,
    inference_steps: 28,
    guidance_scale: 6.5,
    output_count: 2,
    audio_direction: 'trueno grave',
    turbo: 'on',
    ignored: 'drop me',
  })
  assert.deepEqual(video, {
    type: 'prepare_video',
    prompt: 'un castillo flotante',
    modelType: 'video-model',
    durationSeconds: 7.5,
    resolutionPreset: '720p',
    resolution: '1280x720',
    aspectRatio: '16:9',
    negativePrompt: undefined,
    seed: 42,
    inferenceSteps: 28,
    guidanceScale: 6.5,
    outputCount: 2,
    audioDirection: 'trueno grave',
    turbo: true,
  })
  assert.deepEqual(definitions.get('prepare_video').validate(video), [])
  assert.equal(definitions.get('prepare_video').resolve({ type: 'prepare_video', prompt: '' }), null)

  const audio = definitions.get('prepare_audio').resolve({
    type: 'prepare_audio', audio_sub_mode: 'music', prompt: 'heavy metal vocal en español', duration_seconds: 75,
  })
  assert.deepEqual(audio, {
    type: 'prepare_audio', subMode: 'music', prompt: 'heavy metal vocal en español', modelType: undefined,
    durationSeconds: 20, negativePrompt: undefined,
  })

  const model3d = definitions.get('prepare_3d').resolve({
    type: 'prepare_3d', prompt: 'un mago con capa', preset: 'cinematic', seed: 12,
  })
  assert.deepEqual(model3d, {
    type: 'prepare_3d', prompt: 'un mago con capa', modelType: undefined, preset: 'cinematic', seed: 12,
  })
})

test('keeps compute confirmation and exact reference/LoRA semantics', async () => {
  const definitions = await registeredStudioCapabilities()
  const sfx = definitions.get('queue_sfx_pack')
  assert.equal(sfx.resolve({ type: 'queue_sfx_pack', confirm: false, sfx_clips: [{ name: 'hit', prompt: 'hit' }] }), null)
  const pack = sfx.resolve({
    type: 'queue_sfx_pack', confirm: true, visual_style: 'arcade', sfx_clips: [
      { name: 'hit', prompt: 'impact', duration_seconds: 3 },
      { name: '', prompt: 'ignored' },
    ],
  })
  assert.deepEqual(pack, {
    type: 'queue_sfx_pack', style: 'arcade', clips: [{ name: 'hit', prompt: 'impact', durationSeconds: 3 }],
    modelType: undefined, negativePrompt: undefined, confirm: true,
  })
  assert.deepEqual(sfx.validate(pack), [])

  const references = definitions.get('attach_studio_references').resolve({
    type: 'attach_studio_references', reference_output_names: ['a.webp', 'b.webp'], reference_role: 'style',
    replace_existing: false, remove_background: true,
  })
  assert.deepEqual(references, {
    type: 'attach_studio_references', outputNames: ['a.webp', 'b.webp'], role: 'style',
    replaceExisting: false, removeBackground: true,
  })

  const clearLoras = definitions.get('configure_studio_loras').resolve({
    type: 'configure_studio_loras', loras: [], replace_existing: true,
  })
  assert.deepEqual(clearLoras, { type: 'configure_studio_loras', loras: [], replaceExisting: true })
  assert.deepEqual(definitions.get('configure_studio_loras').validate(clearLoras), [])
  assert.equal(definitions.get('configure_studio_loras').resolve({ type: 'configure_studio_loras', loras: [] }), null)
})
