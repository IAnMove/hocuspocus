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

test('queues structured Video3D operations until the lazy animator mounts', async () => {
  const { listenForAgentSceneWorkflow, requestAgentSceneWorkflow } = await import('../src/features/agent/agentUiBus.ts')
  const pending = requestAgentSceneWorkflow({ type: 'create_3d_scene', sceneName: 'Pulse', durationSeconds: 8, width: 1280, height: 720, fps: 30 })
  const unsubscribe = listenForAgentSceneWorkflow(async request => ({ message: `created:${request.sceneName}`, sceneId: request.sceneName }))
  assert.deepEqual(await pending, { message: 'created:Pulse', sceneId: 'Pulse' })
  unsubscribe()
})

test('queues Story visual generation until Story Lab mounts', async () => {
  const { listenForAgentStoryVisualGeneration, requestAgentStoryVisualGeneration } = await import('../src/features/agent/agentUiBus.ts')
  const pending = requestAgentStoryVisualGeneration({ projectId: 'story-1', scope: 'characters', targetNames: ['Iria'] })
  const unsubscribe = listenForAgentStoryVisualGeneration(async request => ({ message: `generated:${request.targetNames[0]}`, assetIds: ['asset-1'] }))
  assert.deepEqual(await pending, { message: 'generated:Iria', assetIds: ['asset-1'] })
  unsubscribe()
})

test('capability knowledge includes every currently executable action family', async () => {
  const { AGENT_CAPABILITIES, buildAgentCapabilityGuide } = await import('../src/features/agent/agentCapabilities.ts')
  const { AGENT_ACTION_TYPES } = await import('../src/features/agent/agentActionTypes.ts')
  assert.deepEqual(
    AGENT_CAPABILITIES.map(item => item.type),
    [...AGENT_ACTION_TYPES],
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

  const created = await reconcileAgentTurnWithRequest('crea el videoclip con la canción seleccionada', { reply: 'Lo preparo.', actions: [] })
  assert.deepEqual(created.actions.map(action => action.type), ['stage_story_music_video', 'start_director_production'])

  const infinitive = await reconcileAgentTurnWithRequest(
    'Genera una versión v2 y úsala para preparar el videoclip y ejecutarlo ahora en Director.',
    { reply: 'Sólo generé la canción.', actions: [] },
  )
  assert.deepEqual(infinitive.actions.map(action => action.type), [
    'stage_story_music_video', 'start_director_production',
  ])

  const versionChoice = await reconcileAgentTurnWithRequest(
    'Genera la v2, usa esa versión —no la v1— para preparar el videoclip y ejecutarlo ahora.',
    { reply: 'Sólo generé la canción.', actions: [] },
  )
  assert.deepEqual(versionChoice.actions.map(action => action.type), [
    'stage_story_music_video', 'start_director_production',
  ])
})

test('keeps a vocal Story song in the UI workflow before launching its videoclip', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Conjuro el himno.',
    actions: [
      { type: 'create_story', title: 'El Himno del Sysadmin', project_type: 'music_video', premise: 'Una guardia nocturna salva la red cantando.' },
      {
        type: 'configure_story_song', target_story_title: 'El Himno del Sysadmin', song_title: 'Sudo, sangra, reinicia',
        song_brief: 'Un himno para administradores de sistemas.', music_style: 'heavy metal español ochentero, voz líder ronca y coro grave',
        lyrics_language: 'Español', instrumental: false, model_type: 'ace_step_v1_5_xl_sft_lm_4b',
        lyrics: '[Verse]\nEn la torre de cristal\n[Chorus]\nSudo, sangra, reinicia', target_duration_seconds: 90,
      },
      { type: 'generate_story_song', target_story_title: 'El Himno del Sysadmin', cue_title: 'Sudo, sangra, reinicia · Español', confirm: true },
      { type: 'stage_story_music_video', target_story_title: 'El Himno del Sysadmin', song_name: 'Sudo, sangra, reinicia · Español', cue_title: 'Sudo, sangra, reinicia · Español', pacing: 'rhythmic', confirm: true },
    ],
  }))
  assert.equal(turn.actions[1].type, 'configure_story_song')
  assert.equal(turn.actions[1].instrumental, false)
  assert.match(turn.actions[1].lyrics, /\[Chorus\]/)
  const reconciled = await reconcileAgentTurnWithRequest(
    'hazme una canción con letra, créala como Story Lab y ejecuta el videoclip', turn,
  )
  assert.deepEqual(reconciled.actions.map(action => action.type), [
    'create_story', 'configure_story_song', 'generate_story_song', 'stage_story_music_video', 'start_director_production',
  ])
  assert.equal(reconciled.actions[2].cueTitle, 'Sudo, sangra, reinicia')
  assert.equal(reconciled.actions[3].cueTitle, 'Sudo, sangra, reinicia')
  assert.equal(reconciled.actions[3].songName, '')
})

test('runtime passes the persisted cue identity to song generation and videoclip staging', async () => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { defaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const original = {
    configureSong: defaultApplicationAdapters.storyLab.configureSong,
    generateSong: defaultApplicationAdapters.storyLab.generateSong,
    stageMusicVideo: defaultApplicationAdapters.storyLab.stageMusicVideo,
  }
  const received = []
  clearExecutionMemory()
  defaultApplicationAdapters.storyLab.configureSong = async action => ({
    message: 'Cue saved', target: { kind: 'story_song', id: 'cue-real', title: 'El Himno del Sysadmin' },
  })
  defaultApplicationAdapters.storyLab.generateSong = async action => {
    received.push(action)
    return { message: 'Song generated', target: { kind: 'story_song', id: 'song-real', title: action.cueTitle }, outputNames: ['song.wav'] }
  }
  defaultApplicationAdapters.storyLab.stageMusicVideo = async action => {
    received.push(action)
    return { message: 'Video staged', target: { kind: 'director_production', id: 'production-real', title: 'Video' } }
  }
  try {
    const results = await executeAgentActions([{
      type: 'configure_story_song', targetStoryTitle: 'El Himno del Sysadmin 3', songTitle: 'El Himno del Sysadmin',
      brief: 'Himno', style: 'metal', lyrics: '[Verse]\nNoche', writeLyrics: false,
      lyricsLanguage: 'Español', instrumental: false, model: 'ace_step_v1_5_xl_sft_lm_4b', durationSeconds: 75,
    }, {
      type: 'generate_story_song', targetStoryTitle: 'El Himno del Sysadmin 3', cueTitle: 'El Himno del Sysadmin · Español', confirm: true,
    }, {
      type: 'stage_story_music_video', targetStoryTitle: 'El Himno del Sysadmin 3', songName: 'El Himno del Sysadmin · Español', cueTitle: 'El Himno del Sysadmin · Español', pacing: 'rhythmic', confirm: true,
    }])
    assert.equal(results.every(result => result.ok), true)
    assert.equal(received[0].cueTitle, 'El Himno del Sysadmin')
    assert.equal(received[1].cueTitle, 'El Himno del Sysadmin')
    assert.equal(received[1].songName, '')

    const secondResults = await executeAgentActions([{
      type: 'configure_story_song', targetStoryTitle: 'El Himno del Sysadmin 3', songTitle: 'El Himno del Sysadmin',
      brief: 'Himno más intenso', style: 'metal con guitarras gemelas', lyrics: '[Verse]\nNoche', writeLyrics: false,
      lyricsLanguage: 'Español', instrumental: false, model: 'ace_step_v1_5_xl_sft_lm_4b', durationSeconds: 75,
    }, {
      type: 'generate_story_song', targetStoryTitle: 'El Himno del Sysadmin 3', cueTitle: 'El Himno del Sysadmin', confirm: true,
    }])
    assert.equal(secondResults.every(result => result.ok), true)
    assert.equal(received.filter(action => action.type === 'generate_story_song').length, 2)
  } finally {
    defaultApplicationAdapters.storyLab.configureSong = original.configureSong
    defaultApplicationAdapters.storyLab.generateSong = original.generateSong
    defaultApplicationAdapters.storyLab.stageMusicVideo = original.stageMusicVideo
    clearExecutionMemory()
  }
})

test('a videoclip request infers music_video even if the model omits project_type', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const parsed = parseAgentTurn(JSON.stringify({
    reply: 'Creo el himno.',
    actions: [{
      type: 'create_story',
      title: 'El Himno del Sysadmin',
      premise: 'Videoclip musical de una guardia nocturna que salva la red cantando.',
      visual_style: 'Classic adult animated style of Heavy Metal 1981',
    }],
  }))
  assert.equal(parsed.actions[0].type, 'create_story')
  assert.equal(parsed.actions[0].projectType, 'music_video')

  const coerced = await reconcileAgentTurnWithRequest(
    'Crea desde cero en Story Lab un videoclip llamado El Himno del Sysadmin y ejecuta el videoclip',
    {
      reply: 'Creo el himno.',
      actions: [{
        type: 'create_story',
        title: 'El Himno del Sysadmin',
        projectType: 'full_story',
        creativeBrief: '',
        premise: 'Una guardia nocturna salva la red cantando.',
        logline: '', synopsis: '', theme: '', ending: '', genre: '', tone: '',
        visualStyle: 'Heavy Metal 1981', worldSummary: '', language: 'es',
        characters: [], locations: [], outlineBeats: [],
      }],
    },
  )
  assert.equal(coerced.actions[0].type, 'create_story')
  assert.equal(coerced.actions[0].projectType, 'music_video')
  assert.deepEqual(coerced.actions.map(action => action.type), [
    'create_story', 'configure_story_song', 'generate_story_song', 'stage_story_music_video', 'start_director_production',
  ])
  assert.equal(coerced.actions[1].writeLyrics, true)
  assert.equal(coerced.actions[1].instrumental, false)
  assert.equal(coerced.actions[1].lyricsLanguage, 'es')
  assert.match(coerced.actions[1].style, /videoclip llamado El Himno/i)
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

test('parses a complete confirmed rhythmic Video3D workflow', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Lanzo el videoclip.', actions: [{
    type: 'create_rhythmic_3d_video', scene_name: 'Concierto arcano', prompt: 'synthwave at 120 BPM',
    visual_output_name: 'wizard.glb', layer_name: 'Mago', duration_seconds: 12,
    cue_source: 'beats', rhythm_profile: 'pulse', intensity: .8, confirm: true,
  }] }))
  assert.deepEqual(turn.actions, [{
    type: 'create_rhythmic_3d_video', sceneName: 'Concierto arcano', musicPrompt: 'synthwave at 120 BPM',
    audioOutputName: '', visualOutputName: 'wizard.glb', layerName: 'Mago', durationSeconds: 12,
    cueSource: 'beats', profile: 'pulse', intensity: .8, confirm: true,
  }])
  const reconciled = await reconcileAgentTurnWithRequest('crea una canción y un vídeo 3D que siga cada beat', turn, [])
  assert.deepEqual(reconciled.actions, turn.actions)
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

test('an explicit local comic request overrides a conflicting MiniMax plan', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const create = {
    type: 'create_comic', title: 'Red encantada', synopsis: 'Una maga repara la red.',
    language: 'Español', styleName: 'Fantasía', characters: [], pages: [{
      title: 'Página 1', stage: 'Inicio', panels: [{ caption: '', dialogue: '', sfx: '', scene: 'La red falla.' }],
    }], panels: [], imageProvider: 'minimax', imageModel: 'image-01',
  }
  const reconciled = await reconcileAgentTurnWithRequest(
    'Crea un cómic y genera todas las imágenes usando el proveedor local.',
    { reply: 'Uso MiniMax.', actions: [create] },
  )

  assert.deepEqual(reconciled.actions.map(action => action.type), ['create_comic', 'generate_comic'])
  assert.equal(reconciled.actions[0].imageProvider, 'maestro')
  assert.equal(reconciled.actions[0].imageModel, '')
  assert.equal(reconciled.actions[1].imageProvider, 'maestro')
  assert.equal(reconciled.actions[1].imageModel, '')
})

test('an explicit multi-page comic rebuilds a misrouted Studio image plan', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const request = 'Crea desde cero un cómic titulado exactamente "La red encantada" con 3 páginas y 4 viñetas distintas por página sobre una maga que repara una red encantada. Rellena la UI de Comics y genera todas las imágenes usando el proveedor local.'
  const reconciled = await reconcileAgentTurnWithRequest(request, {
    reply: 'Preparo una imagen.',
    actions: [
      { type: 'prepare_image', prompt: 'a wizard', model: 'flux2_klein_9b' },
      { type: 'start_generation', confirm: true },
    ],
  })

  assert.deepEqual(reconciled.actions.map(action => action.type), ['create_comic', 'generate_comic'])
  assert.equal(reconciled.actions[0].title, 'La red encantada')
  assert.equal(reconciled.actions[0].pages.length, 3)
  assert.ok(reconciled.actions[0].pages.every(page => page.panels.length === 4))
  assert.equal(reconciled.actions[1].imageProvider, 'maestro')
})

test('music-video production negation keeps song setup but removes stage and start', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const turn = {
    reply: 'Creo todo.',
    actions: [
      {
        type: 'create_story', title: 'Himno', creativeBrief: 'Metal', premise: 'Un himno.',
        projectType: 'music_video', language: 'Español', characters: [], locations: [], outlineBeats: [],
      },
      {
        type: 'configure_story_song', targetStoryTitle: 'Himno', songTitle: 'Himno', brief: 'Metal',
        style: 'Heavy metal', lyrics: '[Verse]\nCódigo y metal', writeLyrics: false,
        lyricsLanguage: 'Español', instrumental: false, model: 'ace_step_v1_5_xl_sft_lm_4b',
      },
      { type: 'generate_story_song', targetStoryTitle: 'Himno', cueTitle: 'Himno', confirm: true },
      { type: 'stage_story_music_video', targetStoryTitle: 'Himno', songName: '', cueTitle: 'Himno', pacing: 'balanced', confirm: true },
      { type: 'start_director_production', targetStoryTitle: 'Himno', kind: 'music_video', confirm: true },
    ],
  }
  const reconciled = await reconcileAgentTurnWithRequest(
    'Genera la primera versión de la canción. Todavía no prepares el videoclip.',
    turn,
  )

  assert.deepEqual(reconciled.actions.map(action => action.type), [
    'create_story', 'configure_story_song', 'generate_story_song',
  ])
})

test('music-video negation repairs an omitted explicit song generation only', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const configure = {
    type: 'configure_story_song', targetStoryTitle: 'Himno', songTitle: 'Guardia nocturna', brief: 'Metal',
    style: 'Heavy metal', lyrics: '[Verse]\nCódigo y metal', writeLyrics: false,
    lyricsLanguage: 'Español', instrumental: false, model: 'ace_step_v1_5_xl_sft_lm_4b',
  }
  const reconciled = await reconcileAgentTurnWithRequest(
    'Genera la primera versión de la canción. Todavía no prepares el videoclip.',
    {
      reply: 'La dejo lista.',
      actions: [
        configure,
        { type: 'stage_story_music_video', targetStoryTitle: 'Himno', songName: '', cueTitle: 'inventado', pacing: 'balanced', confirm: true },
        { type: 'start_director_production', targetStoryTitle: 'Himno', kind: 'music_video', confirm: true },
      ],
    },
  )

  assert.deepEqual(reconciled.actions.map(action => action.type), [
    'configure_story_song', 'generate_story_song',
  ])
  assert.equal(reconciled.actions[1].targetStoryTitle, 'Himno')
  assert.equal(reconciled.actions[1].cueTitle, 'Guardia nocturna')
})

test('music-video negation rebuilds omitted song setup from the created project', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const create = {
    type: 'create_story', title: 'Himno visible', creativeBrief: 'Metal de guardia', premise: 'Una guardia.',
    projectType: 'music_video', language: 'Español', characters: [], locations: [], outlineBeats: [],
  }
  const reconciled = await reconcileAgentTurnWithRequest(
    'Rellena una canción vocal completa en español y genera la primera versión de la canción. Todavía no prepares el videoclip.',
    { reply: 'La forjo.', actions: [create] },
  )

  assert.deepEqual(reconciled.actions.map(action => action.type), [
    'create_story', 'configure_story_song', 'generate_story_song',
  ])
  assert.equal(reconciled.actions[1].targetStoryTitle, 'Himno visible')
  assert.equal(reconciled.actions[1].writeLyrics, true)
  assert.equal(reconciled.actions[1].lyricsLanguage, 'Español')
  assert.equal(reconciled.actions[1].model, 'ace_step_v1_5_xl_sft_lm_4b')
  assert.equal(reconciled.actions[2].cueTitle, 'Himno visible')
})

test('an exact requested episode title overrides the LLM invention', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const action = {
    type: 'create_series_episode', seriesTitle: 'Turno de madrugada', seriesPremise: 'Comedia.',
    seriesLogline: 'Una guardia.', episodeTitle: 'El café que no enfría', episodePremise: 'Incidente nocturno.',
    episodeLogline: 'Todo falla.', genre: 'Comedia', tone: 'Seco', visualStyle: 'Sitcom',
    worldSummary: 'Oficina.', theme: 'Equipo', ending: 'Amanece.', language: 'Español',
    characters: [], locations: [], outlineBeats: ['Inicio', 'Fin'], createIfMissing: true, knownUniverse: false,
  }
  const reconciled = await reconcileAgentTurnWithRequest(
    'Abre Series Lab y crea un episodio titulado exactamente "E2E Episodio 42".',
    { reply: 'Hecho.', actions: [action] },
  )

  assert.equal(reconciled.actions[0].episodeTitle, 'E2E Episodio 42')
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
    const prepare = { type: 'prepare_image', prompt: 'un faro al anochecer', resolutionPreset: 'auto', aspectRatio: 'auto', seed: -1, outputCount: 1 }
    const first = await executeAgentActions([
      prepare,
      { type: 'start_generation', confirm: true },
    ])
    assert.equal(first[0].ok, true)
    assert.equal(first[1].ok, true)
    assert.equal(first[1].report.state, 'queued')
    assert.equal(first[1].report.taskId, 'job-studio-1')
    assert.equal(generationCalls, 1)
    const second = await executeAgentActions([prepare, { type: 'start_generation', confirm: true }])
    assert.match(second[1].message, /Reutilizo/)
    assert.equal(second[1].report.taskId, 'job-studio-1')
    assert.equal(generationCalls, 1)

    useStore.setState({
      jobs: useStore.getState().jobs.map(job => (
        job.id === 'job-studio-1' ? { ...job, status: 'failed', error: 'simulated failure' } : job
      )),
    })
    const retry = await executeAgentActions([prepare, { type: 'start_generation', confirm: true }])
    assert.equal(retry[1].ok, true)
    assert.doesNotMatch(retry[1].message, /Reutilizo/)
    assert.equal(retry[1].report.taskId, 'job-studio-2')
    assert.equal(generationCalls, 2)
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
      assert.equal(useStore.getState().directorAutoMode, true)
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

test('character kit and video editor execute, reuse export id, and reject unsigned export', async () => {
  const { executeAgentActions, parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  clearExecutionMemory()
  let kitLibrary = { version: 1, revision: 0, activeId: '', kits: {} }
  let exportCalls = 0
  let exportPayload = null
  const originalFetch = globalThis.fetch
  const originalLoadOutputs = useStore.getState().loadOutputs
  useStore.setState({ loadOutputs: async () => {} })
  globalThis.fetch = async (input, init) => {
    const url = String(typeof input === 'string' ? input : input.url)
    const method = init?.method || 'GET'
    const json = body => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    if (url.includes('/api/v1/character-kits/library/kits/') && method === 'PATCH') {
      const body = JSON.parse(String(init.body || '{}'))
      kitLibrary = { ...kitLibrary, revision: kitLibrary.revision + 1, activeId: body.kit.id, kits: { ...kitLibrary.kits, [body.kit.id]: body.kit } }
      return json(kitLibrary)
    }
    if (url.includes('/api/v1/character-kits/library')) return json(kitLibrary)
    if (url.includes('/api/v1/outputs')) {
      const audio = [{ name: 'tema.wav', type: 'audio', url: '/outputs/tema.wav' }]
      const video = [{ name: 'clip-a.mp4', type: 'video', url: '/outputs/clip-a.mp4' }]
      const images = [
        { name: 'nora-a.png', type: 'image', url: '/outputs/nora-a.png' },
        { name: 'nora-b.png', type: 'image', url: '/outputs/nora-b.png' },
      ]
      const outputs = url.includes('media_type=audio') ? audio
        : url.includes('media_type=image') ? images
          : [...video, ...audio, ...images]
      return json({ outputs, total: outputs.length })
    }
    if (url.includes('/api/v1/video-editor/probe-audio')) {
      return json({ duration: 4, has_audio: true })
    }
    if (url.includes('/api/v1/video-editor/probe')) {
      return json({ duration: 4, width: 1280, height: 720, fps: 30, has_audio: true, pixel_format: 'yuv420p', has_alpha: false })
    }
    if (url.includes('/api/v1/video-editor/export') && method === 'POST') {
      exportCalls += 1
      exportPayload = JSON.parse(String(init.body || '{}'))
      return json({ job_id: 'export-77', status: 'queued', progress: 0, message: 'Queued', filename: null, url: null, error: null })
    }
    return json({})
  }
  try {
    const createdKit = await executeAgentActions([{ type: 'create_character_kit', name: 'Nora', style: 'cutout' }])
    assert.equal(createdKit[0].ok, true)
    assert.equal(createdKit[0].report.target.kind, 'character_kit')
    const ambiguousReference = await executeAgentActions([{
      type: 'attach_character_kit_references', kitName: 'Nora', outputNames: ['nora-a.png', 'nora-b.png'],
    }])
    assert.equal(ambiguousReference[0].ok, false)
    const attachedReference = await executeAgentActions([{
      type: 'attach_character_kit_references', kitName: 'Nora', outputNames: ['nora-a.png'],
    }])
    assert.equal(attachedReference[0].ok, true)
    assert.equal(kitLibrary.kits[kitLibrary.activeId].identityReference.name, 'nora-a.png')
    const unsigned = parseAgentTurn(JSON.stringify({
      reply: 'Exporto.',
      actions: [{ type: 'export_video_editor', confirm: false }],
    }))
    assert.equal(unsigned.actions.length, 0)
    await executeAgentActions([{ type: 'create_video_editor_project', projectName: 'corte-final' }])
    const wrongProject = await executeAgentActions([{ type: 'open_video_editor_project', projectName: 'otro-corte' }])
    assert.equal(wrongProject[0].ok, false)
    await executeAgentActions([{ type: 'add_video_editor_clips', outputNames: ['clip-a.mp4'] }])
    await executeAgentActions([{ type: 'add_video_editor_audio', outputName: 'tema.wav', clipName: '' }])
    const { loadEditorDraft } = await import('../src/features/video-editor/editorDraft.ts')
    const draft = loadEditorDraft(useStore.getState().activeWorkspace || 'default')
    assert.equal(draft.clips.some(clip => clip.name === 'tema.wav'), false)
    assert.equal(draft.soundtrack?.name, 'tema.wav')
    const exported = await executeAgentActions([{ type: 'export_video_editor', confirm: true }])
    assert.equal(exported[0].ok, true)
    assert.equal(exported[0].report.state, 'queued')
    assert.equal(exported[0].report.taskId, 'export-77')
    assert.equal(exportCalls, 1)
    assert.deepEqual(exportPayload.soundtrack, {
      name: 'tema.wav', source: '/outputs/tema.wav', trim_start: 0, trim_end: 4, volume: 1, loop: false,
    })
    const again = await executeAgentActions([{ type: 'export_video_editor', confirm: true }])
    assert.match(again[0].message, /Reutilizo/)
    assert.equal(again[0].report.taskId, 'export-77')
    assert.equal(exportCalls, 1)
  } finally {
    globalThis.fetch = originalFetch
    useStore.setState({ loadOutputs: originalLoadOutputs })
    clearExecutionMemory()
  }
})

test('track_video_editor_export keeps job status without a filename', async () => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  clearExecutionMemory()
  const originalFetch = globalThis.fetch
  const originalLoadOutputs = useStore.getState().loadOutputs
  useStore.setState({ loadOutputs: async () => {}, activeWorkspace: 'default' })
  let job = {
    job_id: 'export-88',
    status: 'running',
    progress: 40,
    message: 'Codificando el corte',
    filename: null,
    url: null,
    error: null,
  }
  globalThis.fetch = async (input, init) => {
    const url = String(typeof input === 'string' ? input : input.url)
    const method = init?.method || 'GET'
    const json = body => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    if (url.includes('/api/v1/video-editor/export/export-88') && method === 'GET') return json(job)
    return json({})
  }
  window.localStorage.setItem('maestro-video-editor-export-v1:default', 'export-88')
  try {
    await executeAgentActions([{ type: 'create_video_editor_project', projectName: 'corte-final' }])
    const running = await executeAgentActions([{ type: 'track_video_editor_export' }])
    assert.equal(running[0].ok, true)
    assert.equal(running[0].report.state, 'running')
    assert.equal(running[0].report.taskId, 'export-88')
    assert.match(running[0].message, /Codificando el corte/)
    assert.deepEqual(running[0].report.outputNames || [], [])

    job = { ...job, status: 'failed', message: 'FFmpeg se quedó sin disco', error: 'disk' }
    const failed = await executeAgentActions([{ type: 'track_video_editor_export' }])
    assert.equal(failed[0].report.state, 'failed')
    assert.match(failed[0].message, /FFmpeg se quedó sin disco/)
    assert.deepEqual(failed[0].report.outputNames || [], [])
  } finally {
    window.localStorage.removeItem('maestro-video-editor-export-v1:default')
    globalThis.fetch = originalFetch
    useStore.setState({ loadOutputs: originalLoadOutputs })
    clearExecutionMemory()
  }
})

test('track_character_kit_job inspects the canonical queue and stays running', async () => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  clearExecutionMemory()
  let kitLibrary = { version: 1, revision: 0, activeId: '', kits: {} }
  let activityOpened = 0
  const onActivity = () => { activityOpened += 1 }
  window.addEventListener('hocuspocus:activity-details', onActivity)
  const originalFetch = globalThis.fetch
  const originalLoadOutputs = useStore.getState().loadOutputs
  useStore.setState({ loadOutputs: async () => {} })
  globalThis.fetch = async (input, init) => {
    const url = String(typeof input === 'string' ? input : input.url)
    const method = init?.method || 'GET'
    const json = body => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    if (url.includes('/api/v1/character-kits/library/kits/') && method === 'PATCH') {
      const body = JSON.parse(String(init.body || '{}'))
      kitLibrary = { ...kitLibrary, revision: kitLibrary.revision + 1, activeId: body.kit.id, kits: { ...kitLibrary.kits, [body.kit.id]: body.kit } }
      return json(kitLibrary)
    }
    if (url.includes('/api/v1/character-kits/library')) return json(kitLibrary)
    if (url.includes('/api/v1/tasks')) {
      return json({
        workspace: 'default',
        latest_event_id: 1,
        tasks: [{
          id: 'task-kit-1',
          root_id: 'task-kit-1',
          parent_id: null,
          kind: 'generation',
          title: 'Pose base Nora',
          workflow: 'character_kit',
          status: 'running',
          phase: 'render',
          message: 'Generando',
          current: 1,
          total: 2,
          progress: 0.5,
          detail_current: 0,
          detail_total: 0,
          created_at: 1,
          updated_at: 1,
          attempt: 1,
          max_attempts: 1,
          cancelable: true,
          resumable: false,
          recoverable: false,
          resource_requirements: ['gpu'],
        }],
      })
    }
    return json({})
  }
  try {
    await executeAgentActions([{ type: 'create_character_kit', name: 'Nora', style: 'cutout' }])
    const tracked = await executeAgentActions([{ type: 'track_character_kit_job', kitName: 'Nora' }])
    assert.equal(tracked[0].ok, true)
    assert.equal(tracked[0].report.state, 'running')
    assert.equal(tracked[0].report.target.kind, 'character_kit')
    assert.match(tracked[0].message, /Sigo el trabajo de “Nora”/)
    assert.match(tracked[0].message, /Pose base Nora/)
    assert.match(tracked[0].message, /He abierto Activity/)
    assert.ok(activityOpened >= 1)
  } finally {
    window.removeEventListener('hocuspocus:activity-details', onActivity)
    globalThis.fetch = originalFetch
    useStore.setState({ loadOutputs: originalLoadOutputs })
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

test('repairs an explicit Studio audio request when the model only prepares it', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const prepare = {
    type: 'prepare_audio', subMode: 'music', prompt: 'Piano minimalista instrumental',
    modelType: 'ace_step_v1_5_xl_sft_lm_4b', durationSeconds: 15,
  }
  const reconciled = await reconcileAgentTurnWithRequest(
    'Abre Studio → Audio, rellena una canción instrumental de prueba y genérala ahora.',
    { reply: 'La preparo.', actions: [{ type: 'open_tab', tab: 'audio' }, prepare] },
  )

  assert.deepEqual(reconciled.actions.map(action => action.type), ['open_tab', 'prepare_audio', 'start_generation'])
  assert.equal(reconciled.actions[1].prompt, prepare.prompt)

  const retry = await reconcileAgentTurnWithRequest(
    'Abre de nuevo Studio → Audio, conserva los mismos valores visibles y lanza una nueva generación de audio. No reanudes la tarea fallida anterior.',
    { reply: 'Mantengo la ficha.', actions: [{ type: 'open_tab', tab: 'audio' }, prepare] },
  )
  assert.deepEqual(retry.actions.map(action => action.type), ['open_tab', 'prepare_audio', 'start_generation'])
})

test('keeps Story Lab song generation out of the Studio Audio shortcut', async () => {
  const { isExplicitAudioGenerationRequest, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const configure = {
    type: 'configure_story_song', targetStoryTitle: 'Guardia nocturna', songTitle: 'Himno',
    brief: 'Metal de guardia', style: 'Heavy metal', lyrics: '[Verse]\nCódigo y metal',
    writeLyrics: false, lyricsLanguage: 'Español', instrumental: false,
    model: 'ace_step_v1_5_xl_sft_lm_4b',
  }

  assert.equal(isExplicitAudioGenerationRequest('Genera una canción heavy metal en Story Lab.'), false)
  assert.equal(isExplicitAudioGenerationRequest('Abre Studio → Audio y genera una canción heavy metal.'), true)
  assert.equal(isExplicitAudioGenerationRequest('En Studio Audio genera una voz de prueba.'), true)

  const reconciled = await reconcileAgentTurnWithRequest(
    'En Story Lab crea una canción vocal heavy metal y genera su primera versión.',
    {
      reply: 'Forjaré la canción.',
      actions: [
        configure,
        { type: 'generate_story_song', targetStoryTitle: 'Guardia nocturna', cueTitle: 'Himno', confirm: true },
      ],
    },
  )

  assert.deepEqual(reconciled.actions.map(action => action.type), [
    'configure_story_song', 'generate_story_song',
  ])
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

  const studioPronoun = await reconcileAgentTurnWithRequest(
    'Abre Studio → Video, rellena el formulario con un mago ante servidores y genéralo ahora.',
    { reply: 'Lo preparo y lo disparo.', actions: [{ type: 'prepare_video', prompt: 'Mago ante servidores' }] },
  )
  assert.deepEqual(studioPronoun.actions.map(action => action.type), ['prepare_video', 'start_generation'])
})

test('genera el video reuses a prepared Studio prompt instead of asking for a topic', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const original = {
    generationMode: useStore.getState().generationMode,
    params: useStore.getState().params,
    durationSeconds: useStore.getState().durationSeconds,
    savedPromptPerMode: useStore.getState().savedPromptPerMode,
  }
  useStore.setState({
    generationMode: 'video',
    params: { ...useStore.getState().params, prompt: 'Sheldon Cooper cuenta un chiste en su salón, bata verde, Bazinga.' },
    durationSeconds: 5.2,
  })
  const resumed = await reconcileAgentTurnWithRequest('genera el video', { reply: '¿De qué?', actions: [] })
  assert.deepEqual(resumed.actions.map(action => action.type), ['prepare_video', 'start_generation'])
  assert.equal(resumed.actions[0].prompt.includes('Sheldon'), true)
  assert.equal(resumed.actions[0].modelType, undefined)
  assert.equal(resumed.actions[1].confirm, true)

  useStore.setState({
    generationMode: 'video',
    params: { ...useStore.getState().params, prompt: '' },
    savedPromptPerMode: { ...useStore.getState().savedPromptPerMode, video: '' },
  })
  const asked = await reconcileAgentTurnWithRequest('genera el video', { reply: '¿De qué?', actions: [] })
  assert.equal(asked.actions[0].type, 'open_tab')
  assert.equal(asked.actions.some(action => action.type === 'start_generation'), false)
  useStore.setState(original)
})

test('genera el video de un mapache uses the new topic instead of the prepared form', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const original = {
    generationMode: useStore.getState().generationMode,
    params: useStore.getState().params,
    savedPromptPerMode: useStore.getState().savedPromptPerMode,
  }
  useStore.setState({
    generationMode: 'video',
    params: { ...useStore.getState().params, prompt: 'Sheldon Cooper cuenta un chiste en su salón, bata verde, Bazinga.' },
  })
  const topical = await reconcileAgentTurnWithRequest('genera el video de un mapache', { reply: '¿De qué?', actions: [] })
  assert.deepEqual(topical.actions.map(action => action.type), ['prepare_video', 'start_generation'])
  assert.ok(topical.actions[0].prompt.includes('mapache'))
  assert.equal(topical.actions[0].prompt.includes('Sheldon'), false)

  const example = await reconcileAgentTurnWithRequest('genera el video de ejemplo', { reply: '¿De qué?', actions: [] })
  assert.deepEqual(example.actions.map(action => action.type), ['prepare_video', 'start_generation'])
  assert.ok(example.actions[0].prompt.length > 40)
  assert.equal(example.actions[0].prompt.includes('genera el video'), false)
  assert.equal(example.actions[0].prompt.includes('Sheldon'), false)
  useStore.setState(original)
})

test('genera el video does not copy an incompatible I2V, audio or 3D model as T2V', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const original = {
    generationMode: useStore.getState().generationMode,
    params: useStore.getState().params,
    savedPromptPerMode: useStore.getState().savedPromptPerMode,
  }
  const prepared = 'Sheldon Cooper cuenta un chiste en su salón, bata verde, Bazinga.'

  for (const [generationMode, modelType] of [
    ['image', 'image-only-model'],
    ['audio', 'ace_step_music'],
    ['model3d', 'hunyuan3d'],
    ['video', 'i2v-only-model'],
  ]) {
    useStore.setState({
      generationMode,
      params: { ...useStore.getState().params, model_type: modelType, prompt: generationMode === 'video' ? prepared : 'otro modo' },
      savedPromptPerMode: { ...useStore.getState().savedPromptPerMode, video: prepared },
    })
    const turn = await reconcileAgentTurnWithRequest('genera el video', { reply: '¿De qué?', actions: [] })
    assert.deepEqual(turn.actions.map(action => action.type), ['prepare_video', 'start_generation'])
    assert.equal(turn.actions[0].modelType, undefined, `${generationMode}/${modelType} must not be copied as T2V`)
    assert.equal(turn.actions[0].prompt.includes('Sheldon'), true)
  }
  useStore.setState(original)
})
