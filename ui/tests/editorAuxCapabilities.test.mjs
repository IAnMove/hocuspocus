import assert from 'node:assert/strict'
import test from 'node:test'

test('editor auxiliary capabilities register once and expose bounded contracts', async () => {
  const { registerEditorAuxCapabilities } = await import('../src/features/agent/editorAuxCapabilities.ts')
  const definitions = new Map()
  const register = definition => {
    definitions.set(definition.name, definition)
    return definition
  }

  registerEditorAuxCapabilities(register)
  registerEditorAuxCapabilities(register)

  const names = [...definitions.keys()]
  assert.deepEqual(names, [
    'generate_comic_panel',
    'update_character_kit',
    'add_video_editor_clips',
    'order_video_editor_clips',
    'trim_video_editor_clip',
    'add_video_editor_audio',
    'validate_video_editor_timeline',
    'export_video_editor',
    'track_video_editor_export',
  ])
  for (const definition of definitions.values()) {
    assert.equal(definition.inputSchema.additionalProperties, false)
    assert.ok(definition.title)
    assert.ok(definition.description)
    assert.ok(definition.useWhen)
    assert.ok(definition.progress)
    assert.ok(definition.report.targetKind)
    assert.equal(typeof definition.resolve, 'function')
    assert.equal(typeof definition.validate, 'function')
    assert.equal(typeof definition.prepare, 'function')
    assert.equal(typeof definition.execute, 'function')
    assert.equal(typeof definition.correlate, 'function')
    assert.equal(typeof definition.track, 'function')
    assert.equal(typeof definition.summarize, 'function')
  }
})
test('comic panel contract requires positive addressed coordinates and confirmation', async () => {
  const { registerEditorAuxCapabilities } = await import('../src/features/agent/editorAuxCapabilities.ts')
  const definitions = new Map()
  const register = definition => {
    definitions.set(definition.name, definition)
    return definition
  }
  registerEditorAuxCapabilities(register)
  const definition = definitions.get('generate_comic_panel')

  assert.deepEqual(definition.resolve({
    type: 'generate_comic_panel', page_number: 2, panel_number: 4, confirm: true,
  }), { type: 'generate_comic_panel', pageNumber: 2, panelNumber: 4, confirm: true })
  assert.equal(definition.resolve({
    type: 'generate_comic_panel', page_number: 2, panel_number: 4, confirm: false,
  }), null)
  assert.equal(definition.resolve({
    type: 'generate_comic_panel', page_number: 0, panel_number: 4, confirm: true,
  }), null)
  assert.deepEqual(definition.validate({
    type: 'generate_comic_panel', pageNumber: 2, panelNumber: 4, confirm: true,
  }), [])
  assert.notDeepEqual(definition.validate({
    type: 'generate_comic_panel', pageNumber: 2, panelNumber: 4, confirm: false,
  }), [])
})

test('Character Kit and Video Editor contracts preserve parser field names', async () => {
  const { registerEditorAuxCapabilities } = await import('../src/features/agent/editorAuxCapabilities.ts')
  const definitions = new Map()
  const register = definition => {
    definitions.set(definition.name, definition)
    return definition
  }
  registerEditorAuxCapabilities(register)

  const update = definitions.get('update_character_kit')
  assert.deepEqual(update.resolve({
    type: 'update_character_kit', kit_name: 'Luna', title: 'Luna Prime',
    look_notes: 'Capa azul y ojos dorados.', visual_style: 'anime-2d',
  }), {
    type: 'update_character_kit', kitName: 'Luna', name: 'Luna Prime',
    lookNotes: 'Capa azul y ojos dorados.', style: 'anime-2d',
  })
  assert.deepEqual(update.resolve({ type: 'update_character_kit' }), {
    type: 'update_character_kit', kitName: '', name: '', lookNotes: '', style: '',
  })
  assert.notDeepEqual(update.validate({
    type: 'update_character_kit', kitName: '', name: '', lookNotes: '', style: '',
  }), [])

  const add = definitions.get('add_video_editor_clips')
  assert.deepEqual(add.resolve({
    type: 'add_video_editor_clips', reference_output_names: ['  shot-a  ', '', 'shot-b'],
  }), { type: 'add_video_editor_clips', outputNames: ['shot-a', 'shot-b'] })
  const trim = definitions.get('trim_video_editor_clip')
  assert.deepEqual(trim.resolve({
    type: 'trim_video_editor_clip', clip_name: 'shot-a', trim_start: -2, trim_end: 3,
  }), { type: 'trim_video_editor_clip', clipName: 'shot-a', trimStart: 0, trimEnd: 3 })
  assert.equal(trim.resolve({
    type: 'trim_video_editor_clip', clip_name: 'shot-a', trim_start: 3, trim_end: 2,
  }), null)
  const audio = definitions.get('add_video_editor_audio')
  assert.deepEqual(audio.resolve({
    type: 'add_video_editor_audio', audio_output_name: 'himno.mp3', clip_name: 'unused',
  }), { type: 'add_video_editor_audio', outputName: 'himno.mp3', clipName: 'unused' })
  const exportDefinition = definitions.get('export_video_editor')
  assert.equal(exportDefinition.resolve({ type: 'export_video_editor', confirm: false }), null)
  assert.deepEqual(exportDefinition.resolve({ type: 'export_video_editor', confirm: true }), {
    type: 'export_video_editor', confirm: true,
  })
})
