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

test('capability knowledge includes every currently executable action family', async () => {
  const { AGENT_CAPABILITIES, buildAgentCapabilityGuide } = await import('../src/features/agent/agentCapabilities.ts')
  assert.deepEqual(
    AGENT_CAPABILITIES.map(item => item.type),
    ['open_tab', 'prepare_video', 'prepare_image', 'prepare_audio', 'queue_sfx_pack', 'prepare_3d', 'open_story_section', 'open_series_section', 'start_generation', 'create_story', 'update_story', 'generate_story_section', 'apply_story_proposal', 'approve_story_section', 'stage_story_comic', 'create_series_episode', 'update_series_episode', 'create_comic', 'generate_comic', 'generate_comic_panel', 'attach_studio_references', 'configure_studio_loras', 'inspect_queue', 'cancel_task', 'resume_task', 'retry_task', 'select_workspace', 'create_workspace'],
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
