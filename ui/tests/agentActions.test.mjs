import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
})
window.matchMedia = () => ({ matches: false })

test('parses a filled Series Lab episode action without trusting unknown fields', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Voy a preparar el episodio.',
    actions: [{
      type: 'create_series_episode',
      series_title: 'Seinfeld',
      series_premise: 'Comedia cotidiana sobre cuatro amigos en Nueva York.',
      series_logline: 'Pequeños problemas se convierten en grandes enredos.',
      episode_title: 'El sushi del silencio',
      episode_premise: 'El grupo visita un restaurante donde está prohibido hablar.',
      episode_logline: 'Guardar silencio resulta imposible para todos.',
      genre: 'Comedia', tone: 'Seco y observacional', visual_style: 'Sitcom cinematográfica',
      world_summary: 'Nueva York cotidiana y neurótica.', theme: 'La incomunicación',
      ending: 'El silencio se rompe de la forma menos oportuna.', language: 'Español de España',
      characters: [{
        name: 'Jerry', role: 'Protagonista', personality: 'Observador', desire: 'Evitar el drama',
        flaw: 'Distante', appearance: 'Cómico neoyorquino', voice: 'Irónica', ignored: 'drop me',
      }],
      locations: [{ name: 'Silent Fish', purpose: 'Conflicto', description: 'Restaurante minimalista' }],
      outline_beats: ['Llegada', 'Complicación', 'Remate'],
      target_duration_seconds: 75,
      create_if_missing: true,
      known_universe: true,
      ignored: 'drop me',
    }],
  }))

  assert.equal(turn.actions.length, 1)
  assert.equal(turn.actions[0].type, 'create_series_episode')
  assert.equal(turn.actions[0].seriesTitle, 'Seinfeld')
  assert.equal(turn.actions[0].characters[0].name, 'Jerry')
  assert.equal('ignored' in turn.actions[0], false)
})

test('remembers an internal lab destination requested before its lazy panel mounts', async () => {
  const { listenForAgentSeriesSection, openAgentSeriesSection } = await import('../src/features/agent/agentUiBus.ts')
  openAgentSeriesSection('episode')
  let received = ''
  const unsubscribe = listenForAgentSeriesSection(section => { received = section })
  assert.equal(received, 'episode')
  unsubscribe()
})

test('queues a 3D rhythm request until the lazy animator mounts', async () => {
  const { listenForAgentSceneRhythm, requestAgentSceneRhythm } = await import('../src/features/agent/agentUiBus.ts')
  const request = { sceneName: '', layerName: 'Mago', audioOutputName: 'tema.wav', cueSource: 'beats', profile: 'pulse', intensity: .5 }
  const pending = requestAgentSceneRhythm(request)
  const unsubscribe = listenForAgentSceneRhythm(async received => `applied:${received.layerName}`)
  assert.equal(await pending, 'applied:Mago')
  unsubscribe()
})

test('queues a 3D scene control request until the lazy animator mounts', async () => {
  const { listenForAgentSceneControl, requestAgentSceneControl } = await import('../src/features/agent/agentUiBus.ts')
  const request = { type: 'open_3d_scene', sceneName: 'Concierto arcano', layerName: 'Mago' }
  const pending = requestAgentSceneControl(request)
  const unsubscribe = listenForAgentSceneControl(async received => `opened:${received.sceneName}`)
  assert.equal(await pending, 'opened:Concierto arcano')
  unsubscribe()
})

test('queues Story visual generation until Story Lab mounts', async () => {
  const { listenForAgentStoryVisualGeneration, requestAgentStoryVisualGeneration } = await import('../src/features/agent/agentUiBus.ts')
  const pending = requestAgentStoryVisualGeneration({ projectId: 'story-1', scope: 'characters', targetNames: ['Iria'] })
  const unsubscribe = listenForAgentStoryVisualGeneration(async request => `generated:${request.targetNames[0]}`)
  assert.equal(await pending, 'generated:Iria')
  unsubscribe()
})

test('capability knowledge includes every currently executable action family', async () => {
  const { AGENT_CAPABILITIES, buildAgentCapabilityGuide } = await import('../src/features/agent/agentCapabilities.ts')
  assert.deepEqual(
    AGENT_CAPABILITIES.map(item => item.type),
    ['open_tab', 'prepare_video', 'prepare_image', 'prepare_audio', 'queue_sfx_pack', 'prepare_3d', 'open_story_section', 'open_series_section', 'start_generation', 'create_story', 'update_story', 'generate_story_section', 'apply_story_proposal', 'approve_story_section', 'approve_story_visuals', 'generate_story_visuals', 'stage_story_comic', 'stage_story_video', 'stage_story_music_video', 'start_director_production', 'create_series_episode', 'update_series_episode', 'generate_series_plan', 'apply_series_plan', 'render_series_shots', 'review_series_attempts', 'assemble_series_episode', 'commit_series_canon', 'open_3d_scene', 'save_3d_scene', 'export_3d_scene', 'apply_3d_rhythm', 'create_comic', 'generate_comic', 'generate_comic_panel', 'attach_studio_references', 'configure_studio_loras', 'create_character_kit', 'open_character_kit', 'update_character_kit', 'attach_character_kit_references', 'build_character_kit', 'open_character_kit_rig', 'apply_character_kit_preset', 'track_character_kit_job', 'create_video_editor_project', 'open_video_editor_project', 'add_video_editor_clips', 'order_video_editor_clips', 'trim_video_editor_clip', 'add_video_editor_audio', 'validate_video_editor_timeline', 'export_video_editor', 'track_video_editor_export', 'inspect_queue', 'cancel_task', 'resume_task', 'retry_task', 'select_workspace', 'create_workspace'],
  )
  assert.match(buildAgentCapabilityGuide(), /create_series_episode/)
})

test('parses a bounded Story Lab patch and drops an empty one', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Completo el grimorio.',
    actions: [
      {
        type: 'update_story',
        target_story_title: 'La torre de sal',
        synopsis: 'Una cartógrafa descubre que el faro dibuja rutas hacia recuerdos perdidos.',
        characters: [{ name: 'Iria', role: 'Cartógrafa', personality: 'Metódica', desire: 'Encontrar a su hermana', flaw: 'Desconfía de todos', appearance: 'Abrigo azul', voice: 'Serena' }],
        outline_beats: ['El mapa cambia', 'La ruta exige un recuerdo', 'Iria elige qué conservar'],
      },
      { type: 'update_story', target_story_title: 'La torre de sal' },
    ],
  }))
  assert.equal(turn.actions.length, 1)
  assert.equal(turn.actions[0].type, 'update_story')
  assert.equal(turn.actions[0].targetStoryTitle, 'La torre de sal')
  assert.equal(turn.actions[0].characters[0].name, 'Iria')
  assert.deepEqual(turn.actions[0].outlineBeats, ['El mapa cambia', 'La ruta exige un recuerdo', 'Iria elige qué conservar'])
})

test('requires confirmation and a valid scope for Story Lab generation', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Convoco al escriba.',
    actions: [
      { type: 'generate_story_section', target_story_title: 'La torre de sal', story_generation_scope: 'world', instruction: 'Haz más concretas sus reglas.', confirm: true },
      { type: 'generate_story_section', story_generation_scope: 'music', confirm: true },
      { type: 'generate_story_section', story_generation_scope: 'structure', confirm: false },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'generate_story_section',
    targetStoryTitle: 'La torre de sal',
    scope: 'world',
    instruction: 'Haz más concretas sus reglas.',
    confirm: true,
  }])
})

test('requires confirmation before applying a Story Lab proposal', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Sello los cambios.',
    actions: [
      { type: 'apply_story_proposal', target_story_title: 'La torre de sal', confirm: false },
      { type: 'apply_story_proposal', target_story_title: 'La torre de sal', confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'apply_story_proposal',
    targetStoryTitle: 'La torre de sal',
    confirm: true,
  }])
})

test('requires confirmation and an approvable Story Lab section', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Sello la sección.',
    actions: [
      { type: 'approve_story_section', story_section: 'productions', confirm: true },
      { type: 'approve_story_section', story_section: 'world', confirm: false },
      { type: 'approve_story_section', target_story_title: 'La torre de sal', story_section: 'world', confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'approve_story_section',
    targetStoryTitle: 'La torre de sal',
    section: 'world',
    confirm: true,
  }])
})

test('parses confirmed exact Story visual reference selections', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Elijo las referencias.', actions: [{
    type: 'approve_story_visuals', target_story_title: 'La torre de sal', confirm: true,
    story_visual_selections: [
      { target_kind: 'world', target_name: '', asset_name: 'Costa nocturna', primary: false },
      { target_kind: 'character', target_name: 'Iria', asset_name: 'Iria frontal', primary: true },
      { target_kind: 'location', target_name: '', asset_name: 'Faro', primary: false },
    ],
  }] }))
  assert.deepEqual(turn.actions, [{
    type: 'approve_story_visuals', targetStoryTitle: 'La torre de sal', confirm: true,
    selections: [
      { targetKind: 'world', targetName: '', assetName: 'Costa nocturna', primary: false },
      { targetKind: 'character', targetName: 'Iria', assetName: 'Iria frontal', primary: true },
    ],
  }])
})

test('parses confirmed Story visual generation scope and exact targets', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Pinto las identidades.', actions: [
    { type: 'generate_story_visuals', story_visual_scope: 'sets', target_names: [], confirm: true },
    { type: 'generate_story_visuals', target_story_title: 'La torre de sal', story_visual_scope: 'characters', target_names: ['Iria', 'Elías'], confirm: true },
  ] }))
  assert.deepEqual(turn.actions, [{
    type: 'generate_story_visuals', targetStoryTitle: 'La torre de sal', scope: 'characters', targetNames: ['Iria', 'Elías'], confirm: true,
  }])
})

test('parses bounded Story to Comic staging only with confirmation', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Abro el portal al cómic.',
    actions: [
      { type: 'stage_story_comic', page_count: 999, panels_per_page: 0, confirm: false },
      { type: 'stage_story_comic', target_story_title: 'La torre de sal', direction: 'Un capítulo autoconclusivo sobre el mapa.', page_count: 6, panels_per_page: 5, confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'stage_story_comic',
    targetStoryTitle: 'La torre de sal',
    direction: 'Un capítulo autoconclusivo sobre el mapa.',
    pageCount: 6,
    panelsPerPage: 5,
    confirm: true,
  }])
})

test('parses confirmed Story film and trailer staging', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Abro el portal del celuloide.', actions: [
    { type: 'stage_story_video', production_kind: 'music_video', confirm: true },
    { type: 'stage_story_video', production_kind: 'film', confirm: false },
    { type: 'stage_story_video', target_story_title: 'La torre de sal', production_kind: 'trailer', direction: 'Sugiere el misterio sin revelar el final.', duration_seconds: 45, confirm: true },
  ] }))
  assert.deepEqual(turn.actions, [{ type: 'stage_story_video', targetStoryTitle: 'La torre de sal', kind: 'trailer', direction: 'Sugiere el misterio sin revelar el final.', durationSeconds: 45, confirm: true }])
})

test('parses only a confirmed Director production start', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Abro el portal.', actions: [
    { type: 'start_director_production', target_story_title: 'La torre de sal', production_kind: 'series', confirm: true },
    { type: 'start_director_production', target_story_title: 'La torre de sal', production_kind: 'film', confirm: false },
    { type: 'start_director_production', target_story_title: 'La torre de sal', production_kind: 'trailer', confirm: true },
  ] }))
  assert.deepEqual(turn.actions, [{ type: 'start_director_production', targetStoryTitle: 'La torre de sal', kind: 'trailer', confirm: true }])
})

test('parses a confirmed Story music-video staging and start', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const unsigned = parseAgentTurn(JSON.stringify({
    reply: 'Preparo el clip.',
    actions: [{ type: 'stage_story_music_video', song_name: 'Marea', confirm: false }],
  }))
  assert.equal(unsigned.actions.length, 0)
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Preparo el clip.',
    actions: [{
      type: 'stage_story_music_video',
      target_story_title: 'La torre de sal',
      song_name: 'Marea de faro',
      cue_title: 'Tema de Iria',
      pacing: 'rhythmic',
      confirm: true,
    }],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'stage_story_music_video',
    targetStoryTitle: 'La torre de sal',
    songName: 'Marea de faro',
    cueTitle: 'Tema de Iria',
    pacing: 'rhythmic',
    confirm: true,
  }])
  const start = parseAgentTurn(JSON.stringify({
    reply: 'Lanzo.',
    actions: [{ type: 'start_director_production', production_kind: 'music_video', confirm: true }],
  }))
  assert.deepEqual(start.actions, [{ type: 'start_director_production', targetStoryTitle: '', kind: 'music_video', confirm: true }])

  const prepared = await reconcileAgentTurnWithRequest('prepara el videoclip', { reply: '¿Cuál?', actions: [] })
  assert.deepEqual(prepared.actions.map(action => action.type), ['stage_story_music_video'])
  assert.equal(prepared.actions[0].confirm, true)
  const launched = await reconcileAgentTurnWithRequest('inicia el videoclip', { reply: 'Vale.', actions: [] }, [
    { role: 'user', text: 'prepara el videoclip' },
    { role: 'assistant', text: prepared.reply },
  ])
  assert.deepEqual(launched.actions, [{ type: 'start_director_production', targetStoryTitle: '', kind: 'music_video', confirm: true }])
})

test('resolves an exact Story song and cue, and rejects ambiguous names', async () => {
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const { resolveStoryMusicSelection } = await import('../src/features/stories/musicVideoSelection.ts')
  const project = createStoryProject('music_video')
  project.title = 'La torre de sal'
  project.music.candidates = [{
    id: 'cand-1', displayName: 'Marea de faro', title: 'Marea de faro', name: 'marea.mp3',
    source: '/outputs/marea.mp3', prompt: 'coastal hymn', lyrics: 'Sal',
    provider: 'local', model: 'ace_step_v1_5_xl_sft_lm_4b', durationSeconds: 90, createdAt: project.createdAt,
  }]
  project.music.cues = [{
    id: 'cue-1', kind: 'character', targetId: 'char-1', title: 'Tema de Iria', purpose: 'Identidad',
    referenceSong: '', brief: 'faro', style: 'hymn', lyrics: 'Sal', lyriaPrompt: '',
    instrumental: false, durationSeconds: 90, candidates: project.music.candidates, selectedCandidateId: 'cand-1',
  }]
  const exact = resolveStoryMusicSelection(project, 'Marea de faro', 'Tema de Iria')
  assert.equal(exact.candidate.id, 'cand-1')
  assert.equal(exact.cue?.title, 'Tema de Iria')
  const unique = resolveStoryMusicSelection(project, '', '')
  assert.equal(unique.candidate.id, 'cand-1')
  project.music.candidates.push({
    ...project.music.candidates[0], id: 'cand-2', displayName: 'Marea de faro', name: 'marea-2.mp3',
  })
  assert.throws(() => resolveStoryMusicSelection(project, 'Marea de faro', ''), /varias canciones/)
})

test('parses a non-empty Series episode patch without destructive fields', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Retoco el episodio.',
    actions: [
      { type: 'update_series_episode', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio' },
      { type: 'update_series_episode', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio', episode_logline: 'El grupo descubre un local donde discutir está prohibido.', target_duration_seconds: 1800, outline_beats: ['Descubren el local', 'Rompen las reglas', 'El silencio los delata'] },
    ],
  }))
  assert.equal(turn.actions.length, 1)
  assert.equal(turn.actions[0].type, 'update_series_episode')
  assert.equal(turn.actions[0].targetEpisodeTitle, 'El sushi del silencio')
  assert.equal(turn.actions[0].targetDurationSeconds, 1800)
  assert.deepEqual(turn.actions[0].outlineBeats, ['Descubren el local', 'Rompen las reglas', 'El silencio los delata'])
})

test('requires confirmation and a valid Series planning scope', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Convoco la sala de guion.',
    actions: [
      { type: 'generate_series_plan', series_plan_scope: 'render', confirm: true },
      { type: 'generate_series_plan', series_plan_scope: 'complete', confirm: false },
      { type: 'generate_series_plan', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio', series_plan_scope: 'complete', instruction: 'Mantén tres tramas que converjan.', confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'generate_series_plan',
    seriesTitle: 'Mesa para cuatro',
    targetEpisodeTitle: 'El sushi del silencio',
    scope: 'complete',
    instruction: 'Mantén tres tramas que converjan.',
    confirm: true,
  }])
})

test('requires confirmation before applying a Series planning proposal', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Integro el guion.',
    actions: [
      { type: 'apply_series_plan', job_id: 'series-plan-1', confirm: false },
      { type: 'apply_series_plan', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio', job_id: 'series-plan-1', confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'apply_series_plan',
    seriesTitle: 'Mesa para cuatro',
    targetEpisodeTitle: 'El sushi del silencio',
    jobId: 'series-plan-1',
    confirm: true,
  }])
})

test('requires confirmation and selected shot ids for Series rendering', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Enciendo el proyector.',
    actions: [
      { type: 'render_series_shots', render_mode: 'selected', shot_ids: [], confirm: true },
      { type: 'render_series_shots', render_mode: 'all', confirm: false },
      { type: 'render_series_shots', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio', render_mode: 'selected', shot_ids: ['shot-1', 'shot-3'], seed: 42, confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'render_series_shots',
    seriesTitle: 'Mesa para cuatro',
    targetEpisodeTitle: 'El sushi del silencio',
    mode: 'selected',
    shotIds: ['shot-1', 'shot-3'],
    seed: 42,
    confirm: true,
  }])
})

test('parses safe Series review scopes using visible shot numbers', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Examino los ecos del proyector.',
    actions: [
      { type: 'review_series_attempts', review_decision: 'reject', review_scope: 'all_latest', confirm: true },
      { type: 'review_series_attempts', review_decision: 'approve', review_scope: 'selected_latest', shot_numbers: [], confirm: true },
      { type: 'review_series_attempts', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio', review_decision: 'approve', review_scope: 'selected_latest', shot_numbers: [3, 1, 3], confirm: true },
      { type: 'review_series_attempts', review_decision: 'reject', review_scope: 'selected_latest', shot_numbers: [2], attempt_id: 'attempt-7', confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'review_series_attempts', seriesTitle: 'Mesa para cuatro', targetEpisodeTitle: 'El sushi del silencio',
    decision: 'approve', scope: 'selected_latest', shotNumbers: [3, 1], attemptId: '', confirm: true,
  }, {
    type: 'review_series_attempts', seriesTitle: '', targetEpisodeTitle: '',
    decision: 'reject', scope: 'selected_latest', shotNumbers: [2], attemptId: 'attempt-7', confirm: true,
  }])
})

test('requires confirmation before assembling a Series episode', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Uno los fragmentos del espejo.',
    actions: [
      { type: 'assemble_series_episode', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio', confirm: false },
      { type: 'assemble_series_episode', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi del silencio', confirm: true },
    ],
  }))
  assert.deepEqual(turn.actions, [{
    type: 'assemble_series_episode', seriesTitle: 'Mesa para cuatro',
    targetEpisodeTitle: 'El sushi del silencio', confirm: true,
  }])
})

test('parses explicit all or selected Series canon decisions', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Sello la continuidad.', actions: [
    { type: 'commit_series_canon', canon_decision: 'accept_selected', canon_item_ids: [], confirm: true },
    { type: 'commit_series_canon', canon_decision: 'accept_all', canon_item_ids: ['unexpected'], confirm: true },
    { type: 'commit_series_canon', series_title: 'Mesa para cuatro', target_episode_title: 'El sushi', canon_decision: 'reject_selected', canon_item_ids: ['fact-2'], confirm: true },
  ] }))
  assert.deepEqual(turn.actions, [{ type: 'commit_series_canon', seriesTitle: 'Mesa para cuatro', targetEpisodeTitle: 'El sushi', decision: 'reject_selected', itemIds: ['fact-2'], confirm: true }])
})

test('parses a confirmed bounded 3D rhythm request', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'La canción mueve el escenario.', actions: [
    { type: 'apply_3d_rhythm', cue_source: 'bars', rhythm_profile: 'peek', confirm: true },
    { type: 'apply_3d_rhythm', layer_name: 'Mago', audio_output_name: 'tema.wav', cue_source: 'downbeats', rhythm_profile: 'peek', intensity: 2, confirm: true },
  ] }))
  assert.deepEqual(turn.actions, [{ type: 'apply_3d_rhythm', sceneName: '', layerName: 'Mago', audioOutputName: 'tema.wav', cueSource: 'downbeats', profile: 'peek', intensity: 1, confirm: true }])
})

test('parses only confirmed exact 3D scene open and save requests', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Abro y guardo el escenario.', actions: [
    { type: 'open_3d_scene', scene_name: '', layer_name: 'Mago', confirm: true },
    { type: 'open_3d_scene', scene_name: 'Concierto arcano', layer_name: 'Mago', confirm: false },
    { type: 'open_3d_scene', scene_name: 'Concierto arcano', layer_name: 'Mago', confirm: true },
    { type: 'save_3d_scene', scene_name: 'Concierto arcano', confirm: true },
    { type: 'export_3d_scene', scene_name: 'Concierto arcano', confirm: false },
    { type: 'export_3d_scene', scene_name: 'Concierto arcano', confirm: true },
  ] }))
  assert.deepEqual(turn.actions, [
    { type: 'open_3d_scene', sceneName: 'Concierto arcano', layerName: 'Mago', confirm: true },
    { type: 'save_3d_scene', sceneName: 'Concierto arcano', confirm: true },
    { type: 'export_3d_scene', sceneName: 'Concierto arcano', confirm: true },
  ])
})

test('parses bounded Studio references by output name and role', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Adjunto las referencias.',
    actions: [{
      type: 'attach_studio_references',
      reference_output_names: ['portrait-a.png', 'wardrobe-b.webp'],
      reference_role: 'subject',
      replace_existing: true,
      remove_background: true,
    }],
  }))
  assert.deepEqual(turn.actions[0], {
    type: 'attach_studio_references',
    outputNames: ['portrait-a.png', 'wardrobe-b.webp'],
    role: 'subject',
    replaceExisting: true,
    removeBackground: true,
  })
})

test('parses bounded compatible LoRA selections and an explicit clear', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const configured = parseAgentTurn(JSON.stringify({
    reply: 'Configuro los LoRAs.',
    actions: [{
      type: 'configure_studio_loras',
      loras: [{ name: 'cinematic_style.safetensors', weight: 1.25 }],
      replace_existing: true,
    }],
  }))
  assert.deepEqual(configured.actions[0], {
    type: 'configure_studio_loras',
    loras: [{ name: 'cinematic_style.safetensors', weight: 1.25 }],
    replaceExisting: true,
  })
  const cleared = parseAgentTurn(JSON.stringify({
    reply: 'Quito los LoRAs.',
    actions: [{ type: 'configure_studio_loras', loras: [], replace_existing: true }],
  }))
  assert.deepEqual(cleared.actions[0], {
    type: 'configure_studio_loras', loras: [], replaceExisting: true,
  })
})

test('a filled comic includes Director brief, structure, continuity and editable lettering', async () => {
  const { createFilledComic } = await import('../src/features/agent/labActions.ts')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0 }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
  try {
    await createFilledComic({
      type: 'create_comic',
      title: 'La brújula dormida',
      synopsis: 'Una cartógrafa despierta una brújula que sólo señala los lugares olvidados.',
      language: 'Español',
      styleName: 'Aventura europea, tinta azul y acuarela cálida',
      characters: [{
        name: 'Ada', role: 'Cartógrafa', personality: 'Metódica y curiosa',
        desire: 'Encontrar el pueblo borrado', flaw: 'No sabe improvisar',
        appearance: 'Abrigo rojo, pelo negro corto y cartera de mapas', voice: 'Precisa y seca',
      }],
      pages: [], imageProvider: 'profile', imageModel: '',
      panels: [
        { caption: 'El mapa despierta.', dialogue: 'Eso no estaba ahí.', sfx: 'TIC', scene: 'Ada abre un mapa en su taller.' },
        { caption: 'Norte cambia.', dialogue: 'Entonces iremos al oeste.', sfx: 'CLAC', scene: 'La aguja gira hacia una puerta tapiada.' },
        { caption: 'Un lugar recordado.', dialogue: 'Ya sé cómo volver.', sfx: '', scene: 'Ada cruza la puerta y ve el pueblo.' },
      ],
    })
    await Promise.resolve()
  } finally {
    globalThis.fetch = originalFetch
  }

  const project = useComicStore.getState().project
  assert.equal(project.title, 'La brújula dormida')
  assert.ok(project.director?.input.storyContext?.includes('Ada'))
  assert.ok(project.director?.input.worldContext?.includes('Universo visual'))
  assert.ok(project.director?.input.forbiddenElements?.includes('No cambiar'))
  assert.ok(project.director?.input.ending)
  assert.equal(project.director?.plan.storyStructure?.length, 1)
  assert.ok(project.director?.plan.pages[0].panels.every(panel => panel.continuityNotes))
  assert.ok(project.characters[0].wardrobe)
  assert.ok(project.characters[0].visualNotes)
  assert.ok(project.pages[0].elements.some(element => element.type === 'text'))
})

test('parses a multi-page MiniMax comic and a confirmed all-images render', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Creo y dibujo el grimorio.', actions: [{
    type: 'create_comic', title: 'Vida por etapas', synopsis: 'Biografía visual.', image_provider: 'minimax', model_type: 'image-01',
    comic_pages: [
      { title: 'Presentación', stage: 'Quién es', comic_panels: [{ caption: 'Comienza.', dialogue: '', sfx: '', scene: 'Retrato introductorio.' }] },
      { title: 'Infancia', stage: 'Primeros años', comic_panels: [{ caption: 'Aprende.', dialogue: '', sfx: '', scene: 'Un niño ante un ordenador.' }] },
    ],
  }, { type: 'generate_comic', image_provider: 'minimax', confirm: true }] }))
  assert.equal(turn.actions[0].type, 'create_comic')
  assert.equal(turn.actions[0].pages.length, 2)
  assert.equal(turn.actions[0].imageProvider, 'minimax')
  assert.deepEqual(turn.actions[1], {
    type: 'generate_comic', imageProvider: 'minimax', imageModel: '',
    scope: 'missing', pages: [], pilot: false, biographyReview: false, confirm: true,
  })
  const reconciled = await reconcileAgentTurnWithRequest('créalo de cero como nuevo cómic y genera las imágenes con MiniMax', { reply: 'Lo preparo.', actions: [turn.actions[0]] })
  assert.deepEqual(reconciled.actions.map(action => action.type), ['create_comic', 'generate_comic'])
  assert.equal(reconciled.actions[0].imageProvider, 'minimax')
  assert.equal(reconciled.actions[1].imageModel, 'image-01')
  assert.equal(reconciled.actions[1].scope, 'missing')
  assert.match(reconciled.reply, /Estimación: 2 llamadas MiniMax/)
  assert.equal(reconciled.actions[0].type === 'create_comic' && reconciled.actions[1].type === 'generate_comic', true)
  const failed = await reconcileAgentTurnWithRequest('reintenta las fallidas del comic', { reply: 'Vale.', actions: [] }, [
    { role: 'user', text: 'hazme un comic' },
    { role: 'assistant', text: 'He abierto Comics con un plan listo.' },
  ])
  assert.equal(failed.actions[0].scope, 'failed')
  const pilot = await reconcileAgentTurnWithRequest('dibuja la pagina piloto', { reply: 'Vale.', actions: [] }, [
    { role: 'user', text: 'hazme un comic' },
    { role: 'assistant', text: 'He abierto Comics con un plan listo.' },
  ])
  assert.equal(pilot.actions[0].pilot, true)
})

test('como nuevo is not a launch question, how-to stays read-only, and negation does not generate', async () => {
  const { reconcileAgentTurnWithRequest, isComicLaunchHowQuestion, isExplicitComicArtworkRequest } = await import('../src/features/agent/agentActions.ts')
  const history = [
    { role: 'user', text: 'hazme un comic de elon musk' },
    { role: 'assistant', text: 'He abierto Comics con un plan listo.' },
  ]
  assert.equal(isComicLaunchHowQuestion('como nuevo', history), false)
  assert.equal(isExplicitComicArtworkRequest('como nuevo', history), false)
  const how = await reconcileAgentTurnWithRequest('como lo lanzo', { reply: 'Pulsa Render.', actions: [] }, history)
  assert.equal(how.actions.some(action => action.type === 'generate_comic' || action.type === 'start_generation'), false)
  const negated = await reconcileAgentTurnWithRequest('no generes las imagenes del comic', { reply: 'Vale.', actions: [{ type: 'generate_comic', imageProvider: 'minimax', imageModel: 'image-01', confirm: true }] }, history)
  assert.equal(negated.actions.some(action => action.type === 'generate_comic'), false)
})

test('executeAgentActions reports the created comic and reuses an identical generate', async () => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { executionKey, executionReport, rememberExecution, clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
  clearExecutionMemory()
  try {
    const created = await executeAgentActions([{
      type: 'create_comic',
      title: 'Clave reutilizable',
      synopsis: 'Un cómic para comprobar el informe común.',
      language: 'Español',
      styleName: 'Tinta',
      characters: [{
        name: 'Nora', role: 'Guía', personality: 'Firme', desire: 'Mapa',
        flaw: 'Prisa', appearance: 'Abrigo', voice: 'Baja',
      }],
      panels: [{ caption: 'Inicio.', dialogue: '', sfx: '', scene: 'Un taller.' }],
      pages: [],
      imageProvider: 'minimax',
      imageModel: 'image-01',
    }])
    const project = useComicStore.getState().project
    assert.equal(created[0].ok, true)
    assert.equal(created[0].report.state, 'completed')
    assert.equal(created[0].report.target.kind, 'comic')
    assert.equal(created[0].report.target.id, project.id)
    const action = { type: 'generate_comic', imageProvider: 'minimax', imageModel: 'image-01', confirm: true }
    rememberExecution(executionReport({
      state: 'running',
      message: 'Dibujando 21/72.',
      taskId: 'task-keep',
      target: created[0].report.target,
      executionKey: executionKey({
        workspace: 'default',
        type: 'generate_comic',
        targetId: project.id,
        params: action,
      }),
      recoverable: true,
    }))
    const reused = await executeAgentActions([action])
    assert.match(reused[0].message, /Reutilizo/)
    assert.equal(reused[0].report.taskId, 'task-keep')
    assert.equal(reused[0].report.target.id, project.id)
  } finally {
    globalThis.fetch = originalFetch
    clearExecutionMemory()
  }
})

test('start_generation reports the real taskId and an identical repeat reuses it', async () => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  clearExecutionMemory()
  const original = {
    startGeneration: useStore.getState().startGeneration,
    loadModelOptions: useStore.getState().loadModelOptions,
    loadOutputs: useStore.getState().loadOutputs,
    models: useStore.getState().models,
    families: useStore.getState().families,
    modelsLoaded: useStore.getState().modelsLoaded,
    enabledModels: useStore.getState().enabledModels,
    params: useStore.getState().params,
    jobs: useStore.getState().jobs,
  }
  let generationCalls = 0
  useStore.setState({
    modelsLoaded: true,
    loadOutputs: async () => {},
    families: [{ id: 'flux', label: 'Flux', order: 1 }],
    models: [{
      model_type: 'flux-test',
      name: 'Flux Test',
      family: 'flux',
      architecture: 'flux',
      is_i2v: false,
      is_t2v: true,
      guidance_max_phases: 1,
      fps: 1,
      is_downloaded: true,
    }],
    enabledModels: new Set(['flux-test']),
    params: { ...useStore.getState().params, model_type: 'flux-test', prompt: '' },
    jobs: [],
    loadModelOptions: async () => {},
    startGeneration: async () => {
      generationCalls += 1
      useStore.setState({
        jobs: [{
          id: `job-studio-${generationCalls}`,
          status: 'queued',
          progress: 0,
          step: 0,
          totalSteps: 0,
          phase: '',
          message: 'Queued',
          outputFiles: [],
          error: null,
          oomInfo: null,
          createdAt: Date.now(),
        }, ...useStore.getState().jobs],
      })
    },
  })
  try {
    const first = await executeAgentActions([
      { type: 'prepare_image', prompt: 'un faro al anochecer', resolutionPreset: 'auto', aspectRatio: 'auto', seed: -1, outputCount: 1 },
      { type: 'start_generation' },
    ])
    assert.equal(first[0].ok, true)
    assert.equal(first[1].ok, true)
    assert.equal(first[1].report.state, 'queued')
    assert.equal(first[1].report.taskId, 'job-studio-1')
    assert.equal(generationCalls, 1)
    const second = await executeAgentActions([{ type: 'start_generation' }])
    assert.match(second[0].message, /Reutilizo/)
    assert.equal(second[0].report.taskId, 'job-studio-1')
    assert.equal(generationCalls, 1)
  } finally {
    useStore.setState(original)
    clearExecutionMemory()
  }
})

test('create_comic then generate_comic reports the newly created comic id', async () => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
  clearExecutionMemory()
  try {
    const created = await executeAgentActions([{
      type: 'create_comic',
      title: 'El mapa nuevo',
      synopsis: 'Una cartógrafa abre un mapa que no existía.',
      language: 'Español',
      styleName: 'Tinta',
      characters: [{
        name: 'Ada', role: 'Cartógrafa', personality: '', desire: '',
        flaw: '', appearance: 'Abrigo rojo', voice: '',
      }],
      panels: [{ caption: 'El mapa.', dialogue: '', sfx: '', scene: 'Un taller.' }],
      pages: [],
      imageProvider: 'minimax',
      imageModel: 'image-01',
      factualBiography: false,
    }])
    const project = useComicStore.getState().project
    assert.equal(created[0].report.target.id, project.id)
    useComicStore.getState().patchProject({
      director: {
        ...project.director,
        completedPanelIds: project.director.plan.pages.flatMap(page => page.panels.map(panel => panel.id)),
      },
    })
    const generated = await executeAgentActions([{
      type: 'generate_comic', imageProvider: 'minimax', imageModel: 'image-01', confirm: true,
    }])
    assert.equal(generated[0].ok, true)
    assert.equal(generated[0].report.target.id, project.id)
    assert.match(generated[0].message, /ya tenían dibujo|He dibujado/)
  } finally {
    globalThis.fetch = originalFetch
    clearExecutionMemory()
  }
})

test('start_director_production after same-turn stage reports that pipeline, not an older one', async () => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { useStoryStore } = await import('../src/features/stories/store.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  clearExecutionMemory()
  const project = normalizeStoryProject({
    ...createStoryProject(),
    title: 'La torre de sal',
    synopsis: 'Una cartógrafa busca un pueblo borrado del mapa.',
    characters: [{ id: 'char-1', name: 'Iria', role: 'Protagonista', appearance: 'Abrigo rojo' }],
    productions: [{
      id: 'prod-old',
      kind: 'film',
      title: 'Producción vieja',
      createdAt: new Date().toISOString(),
      sourceVersion: 1,
      sourceSnapshot: {},
      targetName: 'Vieja',
      targetSnapshot: { pipelineId: 'pipe-old' },
      status: 'running',
    }],
  })
  let library = {
    version: 2,
    revision: 1,
    activeId: project.id,
    projects: { [project.id]: project },
  }
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    const url = String(typeof input === 'string' ? input : input.url)
    if (url.includes('/api/v1/stories/library') && (!init?.method || init.method === 'GET')) {
      return new Response(JSON.stringify(library), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.includes('/api/v1/stories/library') && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body || '{}'))
      library = body.library || library
      library = { ...library, revision: (library.revision || 0) + 1 }
      return new Response(JSON.stringify(library), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  const originalPipeline = useStore.getState().startDirectorPipeline
  const originalLoadOptions = useStore.getState().loadModelOptions
  const originalLoadOutputs = useStore.getState().loadOutputs
  const originalPoll = useStore.getState().pollPipelineStatus
  let pipelineStarts = 0
  useStore.setState({
    pipelineId: null,
    pipelinePolling: false,
    directorLoading: false,
    directorStoryProductionHandoff: {
      workspace: 'default',
      projectId: project.id,
      productionId: 'prod-old',
    },
    loadModelOptions: async () => {},
    loadOutputs: async () => {},
    pollPipelineStatus: () => {},
    startDirectorPipeline: async () => {
      pipelineStarts += 1
      useStore.setState({ pipelineId: `pipe-new-${pipelineStarts}`, pipelinePolling: false })
    },
  })
  useStoryStore.setState({
    workspace: 'default',
    project,
    projects: { [project.id]: project },
    libraryRevision: 1,
    dirty: false,
    hydrated: true,
    loading: false,
    saveError: null,
    libraryConflicts: [],
    activeProjectOperations: {},
  })
  try {
    const results = await executeAgentActions([
      { type: 'start_director_production', targetStoryTitle: '', kind: 'film', confirm: true },
      { type: 'stage_story_video', targetStoryTitle: '', kind: 'film', direction: '', durationSeconds: 45, confirm: true },
    ])
    assert.deepEqual(results.map(item => item.action.type), ['stage_story_video', 'start_director_production'])
    assert.equal(results[0].ok, true, results[0].message)
    assert.equal(results[1].ok, true, results[1].message)
    assert.equal(results[1].report.state, 'running')
    assert.equal(results[1].report.pipelineId, 'pipe-new-1')
    assert.notEqual(results[1].report.pipelineId, 'pipe-old')
    assert.notEqual(results[1].report.target.id, 'prod-old')
    assert.equal(pipelineStarts, 1)
    const stagedId = results[1].report.target.id
    const repeat = await executeAgentActions([
      { type: 'start_director_production', targetStoryTitle: '', kind: 'film', confirm: true },
    ])
    assert.match(repeat[0].message, /Reutilizo/)
    assert.equal(repeat[0].report.pipelineId, 'pipe-new-1')
    assert.equal(repeat[0].report.target.id, stagedId)
    assert.equal(pipelineStarts, 1)
  } finally {
    globalThis.fetch = originalFetch
    useStore.setState({
      startDirectorPipeline: originalPipeline,
      loadModelOptions: originalLoadOptions,
      loadOutputs: originalLoadOutputs,
      pollPipelineStatus: originalPoll,
      pipelineId: null,
      pipelinePolling: false,
      directorStoryProductionHandoff: null,
    })
    useStoryStore.setState({
      hydrated: false,
      loading: false,
      libraryConflicts: [],
      activeProjectOperations: {},
    })
    clearExecutionMemory()
  }
})

test('compute comic render without confirm is dropped', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Dibujo.',
    actions: [{ type: 'generate_comic', image_provider: 'minimax', confirm: false }],
  }))
  assert.equal(turn.actions.length, 0)
})

test('drops cancel_task unless confirm is true and repairs an explicit cancel request', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const unsigned = parseAgentTurn(JSON.stringify({
    reply: 'Cancelo.',
    actions: [{ type: 'cancel_task', task_id: 'task-1', confirm: false }],
  }))
  assert.equal(unsigned.actions.length, 0)
  const signed = parseAgentTurn(JSON.stringify({
    reply: 'Cancelo.',
    actions: [{ type: 'cancel_task', task_id: 'task-1', confirm: true }],
  }))
  assert.equal(signed.actions[0].type, 'cancel_task')
  assert.equal(signed.actions[0].taskId, 'task-1')
  const repaired = await reconcileAgentTurnWithRequest('cancela el trabajo activo', { reply: 'Vale.', actions: [] })
  assert.equal(repaired.actions[0].type, 'cancel_task')
  assert.equal(repaired.actions[0].confirm, true)
})

test('requires confirmation for retry and resolves an explicit latest failure request', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const unsigned = parseAgentTurn(JSON.stringify({
    reply: 'Reintento.', actions: [{ type: 'retry_task', task_id: 'task-9', confirm: false }],
  }))
  assert.equal(unsigned.actions.length, 0)
  const repaired = await reconcileAgentTurnWithRequest(
    'reintenta el último fallo',
    { reply: 'Vale.', actions: [] },
  )
  assert.deepEqual(repaired.actions[0], {
    type: 'retry_task', taskId: 'latest', confirm: true,
  })
})

test('parses only named workspace selection and creation actions', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Cambio de taller.',
    actions: [
      { type: 'select_workspace', workspace_name: 'Proyecto Faro' },
      { type: 'create_workspace', workspace_name: 'Proyecto Puerto' },
      { type: 'create_workspace', workspace_name: '' },
    ],
  }))
  assert.deepEqual(turn.actions, [
    { type: 'select_workspace', workspaceName: 'Proyecto Faro' },
    { type: 'create_workspace', workspaceName: 'Proyecto Puerto' },
  ])
})

test('repairs an explicit image request into prepare_image plus start_generation', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const parsed = parseAgentTurn(JSON.stringify({
    reply: 'Voy a pintar.',
    actions: [{ type: 'prepare_image', prompt: 'un gato naranja', resolution_preset: 'auto', aspect_ratio: '1:1' }],
  }))
  assert.equal(parsed.actions[0].type, 'prepare_image')
  const repaired = await reconcileAgentTurnWithRequest('hazme una imagen de un gato naranja', { reply: '¿Qué estilo?', actions: [] })
  assert.deepEqual(repaired.actions.map(action => action.type), ['prepare_image', 'start_generation'])
  assert.equal(repaired.actions[0].prompt.includes('gato'), true)
})

test('accepts compact open_tab aliases and queues an explicit game SFX pack', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const compact = parseAgentTurn(JSON.stringify({
    reply: 'Voy a Studio.',
    actions: [{ type: 'opentab', tab: 'studio' }],
  }))
  assert.equal(compact.actions[0].type, 'open_tab')
  assert.equal(compact.actions[0].tab, 'studio')
  const unsigned = parseAgentTurn(JSON.stringify({
    reply: 'Pack.',
    actions: [{ type: 'queue_sfx_pack', confirm: false, sfx_clips: [{ name: 'coin', prompt: 'coin', duration_seconds: 1 }] }],
  }))
  assert.equal(unsigned.actions.length, 0)
  const repaired = await reconcileAgentTurnWithRequest(
    'necesito efectos para un juego tipo vampire survivors, puedes ir creando',
    { reply: 'Vale.', actions: [] },
  )
  assert.equal(repaired.actions[0].type, 'queue_sfx_pack')
  assert.equal(repaired.actions[0].confirm, true)
  assert.ok(repaired.actions[0].clips.length >= 10)
})

test('parses collapsed SFX pack keys and ignores trailing JSON junk', async () => {
  const { parseAgentTurn, humanReply } = await import('../src/features/agent/agentActions.ts')
  const messy = '{"reply":"Encolo el pack.\\n\\n1. coin_pickup — brillo corto.\\n2. level_up — fanfarria.","actions":[{"type":"queuesfxpack","sfxclips":[{"name":"coin_pickup","prompt":"coin sparkle","durationseconds":0.5},{"name":"level_up","prompt":"fanfare","durationseconds":1.2}],"confirm":true,"modeltype":"","negativeprompt":"music"}]}"}'
  const turn = parseAgentTurn(messy)
  assert.equal(turn.actions[0].type, 'queue_sfx_pack')
  assert.equal(turn.actions[0].clips.length, 2)
  assert.equal(turn.actions[0].clips[0].name, 'coin_pickup')
  assert.match(humanReply(messy), /Encolo el pack/)
  assert.doesNotMatch(humanReply(messy), /queuesfxpack/)
})

test('repairs an explicit 3D request into prepare_3d plus start_generation', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const repaired = await reconcileAgentTurnWithRequest('hazme un modelo 3d de una copa de ajo', { reply: '¿De qué tamaño?', actions: [] })
  assert.deepEqual(repaired.actions.map(action => action.type), ['prepare_3d', 'start_generation'])
})

test('bare create asks instead of inventing, then an example follow-up fills a distinct comic', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const parsed = parseAgentTurn(JSON.stringify({
    reply: 'Voy a montar el cómic.',
    actions: [{
      type: 'create_comic',
      title: 'Sopa de antena',
      synopsis: 'Dos vecinos.',
      visual_style: 'Tira',
      language: 'Español',
      characters: [{
        name: 'Rosa', role: 'Vecina', personality: '', desire: '', flaw: '',
        appearance: 'Bata', voice: '',
      }],
      comic_panels: [
        { caption: 'Tejado.', dialogue: 'La sopa está rara.', sfx: '' },
        { caption: '', dialogue: 'Mejor pizza.', sfx: 'DING' },
      ],
    }],
  }))
  assert.equal(parsed.actions[0].type, 'create_comic')
  assert.equal(parsed.actions[0].panels.length, 2)
  assert.equal(parsed.actions[0].panels[0].dialogue.includes('sopa'), true)

  const asked = await reconcileAgentTurnWithRequest('hazme un comic', { reply: '¿De qué?', actions: [] })
  assert.equal(asked.actions[0].type, 'open_tab')
  assert.equal(asked.actions[0].tab, 'comics')
  assert.equal(asked.actions.some(action => action.type === 'create_comic'), false)

  const history = [
    { role: 'user', text: 'hazme un comic' },
    { role: 'assistant', text: asked.reply },
  ]
  const first = await reconcileAgentTurnWithRequest('hazme uno de ejemplo', { reply: '¿Cuál?', actions: [] }, history)
  assert.equal(first.actions[0].type, 'create_comic')
  assert.ok(first.actions[0].title.length > 3)
  assert.ok(first.actions[0].panels.length >= 3)

  const second = await reconcileAgentTurnWithRequest('hazme uno de ejemplo', { reply: '¿Cuál?', actions: [] }, [
    ...history,
    { role: 'user', text: 'hazme uno de ejemplo' },
    { role: 'assistant', text: `He abierto Comics con “${first.actions[0].title}”.` },
  ])
  assert.equal(second.actions[0].type, 'create_comic')
  assert.notEqual(second.actions[0].title, first.actions[0].title)

  const unsigned = parseAgentTurn(JSON.stringify({
    reply: 'Dibujo.',
    actions: [{ type: 'generate_comic', confirm: false }],
  }))
  assert.equal(unsigned.actions.length, 0)
  const how = await reconcileAgentTurnWithRequest('como lo lanzo?', { reply: 'Pulsa Render page.', actions: [] }, [
    { role: 'user', text: 'hazme un comic de ejemplo' },
    { role: 'assistant', text: first.reply },
  ])
  assert.equal(how.actions[0].type, 'open_tab')
  assert.equal(how.actions.some(action => action.type === 'generate_comic'), false)
  assert.match(how.reply, /Generate all images/)
  assert.match(how.reply, /l[aá]nzalo/)
  const launch = await reconcileAgentTurnWithRequest('lanzalo ya', { reply: 'Vale.', actions: [] }, [
    { role: 'user', text: 'hazme un comic de ejemplo' },
    { role: 'assistant', text: first.reply },
  ])
  assert.equal(launch.actions[0].type, 'generate_comic')
  assert.equal(launch.actions[0].confirm, true)

  const single = await reconcileAgentTurnWithRequest('regenera la viñeta 2', { reply: 'Vale.', actions: [] }, [
    { role: 'user', text: 'hazme un comic de ejemplo' },
    { role: 'assistant', text: first.reply },
  ])
  assert.deepEqual(single.actions[0], {
    type: 'generate_comic_panel', pageNumber: 1, panelNumber: 2, confirm: true,
  })

  const parsedSingle = parseAgentTurn(JSON.stringify({
    reply: 'Regenero una viñeta.',
    actions: [{
      type: 'generate_comic_panel', page_number: 2, panel_number: 3, confirm: true,
    }],
  }))
  assert.deepEqual(parsedSingle.actions[0], {
    type: 'generate_comic_panel', pageNumber: 2, panelNumber: 3, confirm: true,
  })
})

test('a video example fills a real prompt instead of asking, and a topical video still generates', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const bare = await reconcileAgentTurnWithRequest('hazme un video', { reply: '¿De qué?', actions: [] })
  assert.equal(bare.actions[0].type, 'open_tab')
  assert.equal(bare.actions.some(action => action.type === 'start_generation'), false)

  const example = await reconcileAgentTurnWithRequest('hazme un video de ejemplo', { reply: '¿De qué?', actions: [] })
  assert.deepEqual(example.actions.map(action => action.type), ['prepare_video', 'start_generation'])
  assert.ok(example.actions[0].prompt.length > 40)
  assert.equal(example.actions[0].prompt.includes('hazme un video'), false)

  const topical = await reconcileAgentTurnWithRequest('hazme un video de un mapache con chubasquero', { reply: '¿Qué estilo?', actions: [] })
  assert.deepEqual(topical.actions.map(action => action.type), ['prepare_video', 'start_generation'])
  assert.ok(topical.actions[0].prompt.includes('mapache'))
})
