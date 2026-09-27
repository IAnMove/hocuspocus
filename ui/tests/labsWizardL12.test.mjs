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

function emptyLabs() {
  return {
    story: { project_id: '', active_cue_title: '', selected_song_id: '' },
    series: { series_id: '', episode_id: '', shots: 0, approved: 0 },
  }
}

test('L12: asking what Series Lab can do lists capabilities and does not mutate', async () => {
  const {
    isLabsInventoryQuestion,
    reconcileAgentTurnWithRequest,
  } = await import('../src/features/agent/agentActions.ts')
  const { projectWizardContextCapabilities } = await import('../src/features/agent/wizardCapabilityAvailability.ts')

  assert.equal(isLabsInventoryQuestion('¿Qué puedes hacer en Series Lab?'), true)
  assert.equal(isLabsInventoryQuestion('what can you do in Story Lab'), true)
  assert.equal(isLabsInventoryQuestion('genera los planos pendientes'), false)

  const snapshot = projectWizardContextCapabilities({
    location: { tab: 'series_lab' },
    labs: {
      story: { project_id: '', active_cue_title: '', selected_song_id: '' },
      series: { series_id: 'series-1', episode_id: 'ep-1', shots: 2, approved: 2 },
    },
  })
  assert.ok(snapshot.available.includes('create_series_episode'))
  assert.ok(snapshot.available.includes('assemble_series_episode'))
  assert.ok(snapshot.blocked.every(item => item.reason))

  const turn = await reconcileAgentTurnWithRequest('¿Qué puedes hacer en Series Lab?', {
    reply: 'Creo un episodio y lo renderizo.',
    actions: [
      { type: 'create_series_episode', seriesTitle: 'Taller', episodePremise: 'x', createIfMissing: true },
      { type: 'render_series_shots', renderMode: 'missing', confirm: true },
    ],
  })
  assert.deepEqual(turn.actions, [])
})

test('L12: how-to generate a chapter explains and does not enqueue', async () => {
  const {
    isHowToGenerateQuestion,
    reconcileAgentTurnWithRequest,
  } = await import('../src/features/agent/agentActions.ts')
  assert.equal(isHowToGenerateQuestion('¿Cómo genero un capítulo?'), true)
  const turn = await reconcileAgentTurnWithRequest('¿Cómo genero un capítulo?', {
    reply: 'Lo genero ahora.',
    actions: [
      { type: 'open_tab', tab: 'series_lab' },
      { type: 'create_series_episode', seriesTitle: 'Taller', episodePremise: 'x', createIfMissing: true },
      { type: 'render_series_shots', renderMode: 'missing', confirm: true },
    ],
  })
  assert.deepEqual(turn.actions.map(action => action.type), ['open_tab'])
})

test('L12: opening characters of a quick clip resolves a visible destination', async () => {
  const { resolveStoryLabNavigation, describeStoryLabNavigation } = await import('../src/features/stories/labNavigation.ts')
  const { registerNavigationQueueCapabilities } = await import('../src/features/agent/navigationQueueCapabilities.ts')
  const { useStoryStore, createStoryProject } = await import('../src/features/stories/store.ts')

  const resolved = resolveStoryLabNavigation('characters', 'quick_video')
  assert.equal(resolved.ok, true)
  assert.equal(resolved.tab, 'overview')
  assert.equal(resolved.equivalent, true)
  assert.match(describeStoryLabNavigation(resolved), /overview/)
  assert.doesNotMatch(describeStoryLabNavigation(resolved), /Story Lab → characters\.$/)

  const definitions = new Map()
  registerNavigationQueueCapabilities(definition => {
    definitions.set(definition.name, definition)
    return definition
  })
  const quick = createStoryProject('quick_video')
  useStoryStore.setState({ project: quick, projects: { [quick.id]: quick } })
  const outcome = await definitions.get('open_story_section').execute(
    { type: 'open_story_section', section: 'characters' },
    {
      adapters: {
        storyLab: {
          async open() {
            return { message: 'Opened', target: { kind: 'application_section', id: 'story_lab', title: 'Story Lab' } }
          },
        },
      },
    },
  )
  assert.match(outcome.message, /overview/)
  assert.doesNotMatch(outcome.message, /Story Lab → characters\.$/)
})

test('L12: creating an episode does not incidentally approve pending canon', async () => {
  const { shouldApproveCanonForExplicitEpisodeCreate } = await import('../src/features/series/canonPolicy.ts')
  const pending = shouldApproveCanonForExplicitEpisodeCreate({
    createdSeries: false,
    previousApproval: 'draft',
    previousWorldSummary: 'Un pueblo costero.',
    previousCharacterCount: 3,
  })
  assert.equal(pending.approve, false)
  assert.match(pending.reason, /unrelated canon/)
})

test('L12: a quoted dialogue replacement stays literal and finds affected shots', async () => {
  const { planShotDialogueFromScript, syncShotsFromScript } = await import('../src/features/series/shotDialogueSync.ts')
  const script = [{
    id: 'scene-1',
    dialogue: [{ id: 'd1', characterId: 'ada', text: 'He descubierto ChatGPT' }],
  }]
  const shots = [{
    id: 'shot-1', sceneId: 'scene-1', order: 1, camera: 'locked',
    dialogueBeats: [{ id: 's1', characterId: 'ada', text: 'Hola' }],
    attempts: [{ id: 'attempt-1' }],
  }]
  const plan = planShotDialogueFromScript(script, shots)
  assert.equal(plan[0].status, 'stale')
  const synced = syncShotsFromScript(script, shots)
  assert.equal(synced.shots[0].dialogueBeats[0].text, 'He descubierto ChatGPT')
  assert.deepEqual(synced.shots[0].attempts, [{ id: 'attempt-1' }])
})

test('L12: pending-take review keeps chosen finals; take 2 can replace one shot', async () => {
  const { bulkApproveSelections } = await import('../src/features/series/shotReviewPolicy.ts')
  const { parseRegisteredCapability } = await import('../src/features/agent/capabilityRegistry.ts')
  const hasAsset = () => true
  const shots = [
    {
      id: 'shot-1',
      approvedAttemptId: 'final-1',
      attempts: [
        { id: 'final-1', status: 'completed', outputAssetIds: ['a'] },
        { id: 'newer', status: 'completed', outputAssetIds: ['b'] },
      ],
    },
    {
      id: 'shot-2',
      attempts: [
        { id: 'take-1', status: 'completed', outputAssetIds: ['c'] },
        { id: 'take-2', status: 'completed', outputAssetIds: ['d'] },
      ],
    },
  ]
  const pending = bulkApproveSelections(shots, hasAsset, { replaceFinals: false })
  assert.deepEqual(pending.selections, [{ shotId: 'shot-2', attemptId: 'take-2' }])
  assert.equal(pending.kept, 1)

  const selected = parseRegisteredCapability('review_series_attempts', {
    type: 'review_series_attempts',
    review_decision: 'approve',
    review_scope: 'selected_latest',
    shot_numbers: [2],
    confirm: true,
  })
  assert.equal(selected?.type, 'review_series_attempts')
  assert.equal(selected.scope, 'selected_latest')
  assert.deepEqual(selected.shotNumbers, [2])
})

test('L12: comic staging uses the existing operation; assembly names missing takes', async () => {
  const { parseRegisteredCapability } = await import('../src/features/agent/capabilityRegistry.ts')
  const { missingAssemblyShotOrders } = await import('../src/features/series/shotReviewPolicy.ts')
  const comic = parseRegisteredCapability('stage_series_comic', {
    type: 'stage_series_comic',
    series_title: 'Mesa',
    target_episode_title: 'Piloto',
    page_count: 6,
    panels_per_page: 5,
    confirm: true,
  })
  assert.equal(comic?.type, 'stage_series_comic')
  const missing = missingAssemblyShotOrders([
    { order: 1, attempts: [] },
    {
      order: 2,
      approvedAttemptId: 'ok',
      attempts: [{ id: 'ok', status: 'completed', outputAssetIds: ['clip'] }],
    },
  ], id => id === 'clip')
  assert.deepEqual(missing, [1])
})

test('L12: duplicate titles and invalid provider fields do not silently apply', async () => {
  const { parseRegisteredCapability } = await import('../src/features/agent/capabilityRegistry.ts')
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  assert.equal(parseRegisteredCapability('create_series_episode', {
    type: 'create_series_episode',
  }), null)
  assert.equal(parseRegisteredCapability('render_series_shots', {
    type: 'render_series_shots',
    render_mode: 'turbo-magic',
    confirm: true,
  }), null)
  const missing = parseRegisteredCapability('render_series_shots', {
    type: 'render_series_shots',
    render_mode: 'missing',
    confirm: true,
  })
  assert.equal(missing?.type, 'render_series_shots')
  assert.equal(missing.mode, 'missing')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Lo hago.',
    actions: [{ type: 'not_a_real_action', confirm: true }],
  }))
  assert.deepEqual(turn.actions, [])
})

test('L12: pending Wizard question identity survives reload; in-flight songs reuse the same candidate', async () => {
  const { normalizeWizardContextSnapshot } = await import('../src/features/agent/wizardContext.ts')
  const { reusableInFlightSongCandidate } = await import('../src/features/stories/storySongJobPhases.ts')
  const snapshot = normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1' },
    pending_question: {
      workflow_id: 'workflow-1', step_id: 'step-2', title: 'Pregunta humana', reason: 'Falta una opción',
    },
  })
  assert.equal(snapshot.pending_question?.id, 'question:workflow-1:step-2')
  const again = normalizeWizardContextSnapshot({
    workspace: { id: 'workspace-1' },
    pending_question: {
      workflow_id: 'workflow-1', step_id: 'step-2', title: 'Otra redacción', reason: 'Sigue pendiente',
    },
  })
  assert.equal(again.pending_question?.id, snapshot.pending_question?.id)
  const pending = reusableInFlightSongCandidate([
    { id: 'song-old', status: 'failed', source: '', name: '', prompt: '', lyrics: '', provider: 'local', model: '', durationSeconds: 1, createdAt: '' },
    {
      id: 'song-live', status: 'pending', source: '', name: '', prompt: '', lyrics: '', provider: 'local',
      model: '', durationSeconds: 1, createdAt: '', provenance: { jobId: 'job-live' }, executionPhase: 'accepted',
    },
  ])
  assert.equal(pending?.id, 'song-live')
})
