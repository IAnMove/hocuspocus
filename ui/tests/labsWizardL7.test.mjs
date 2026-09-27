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

test('new Story projects default to direct flow and existing documents keep guided', async () => {
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  assert.equal(createStoryProject().workflowMode, 'automatic')
  assert.equal(createStoryProject('music_video').workflowMode, 'automatic')
  const legacy = normalizeStoryProject({
    ...createStoryProject(),
    workflowMode: undefined,
  })
  assert.equal(legacy.workflowMode, 'guided')
  const kept = normalizeStoryProject({
    ...createStoryProject(),
    workflowMode: 'guided',
  })
  assert.equal(kept.workflowMode, 'guided')
})

test('episode creation may approve only a brand-new canon base', async () => {
  const { shouldApproveCanonForExplicitEpisodeCreate } = await import('../src/features/series/canonPolicy.ts')
  assert.equal(shouldApproveCanonForExplicitEpisodeCreate({
    createdSeries: true,
    previousApproval: 'draft',
    previousWorldSummary: '',
    previousCharacterCount: 0,
  }).approve, true)
  assert.equal(shouldApproveCanonForExplicitEpisodeCreate({
    createdSeries: false,
    previousApproval: 'draft',
    previousWorldSummary: '',
    previousCharacterCount: 0,
  }).approve, true)
  const pending = shouldApproveCanonForExplicitEpisodeCreate({
    createdSeries: false,
    previousApproval: 'draft',
    previousWorldSummary: 'Un pueblo costero.',
    previousCharacterCount: 3,
  })
  assert.equal(pending.approve, false)
  assert.match(pending.reason, /unrelated canon/)
  assert.equal(shouldApproveCanonForExplicitEpisodeCreate({
    createdSeries: false,
    previousApproval: 'approved',
    previousWorldSummary: 'Un pueblo costero.',
    previousCharacterCount: 3,
  }).approve, false)
})

test('LLM confirm is not enough to apply or mark reviewed unless the user asked', async () => {
  const {
    reconcileAgentTurnWithRequest,
    requestAuthorizesEditorialCommit,
  } = await import('../src/features/agent/agentActions.ts')
  assert.equal(requestAuthorizesEditorialCommit('aplica la propuesta'), true)
  assert.equal(requestAuthorizesEditorialCommit('marca revisado el mundo'), true)
  assert.equal(requestAuthorizesEditorialCommit('hazme un episodio de ejemplo'), false)
  const stripped = await reconcileAgentTurnWithRequest('crea un episodio titulado exactamente "Piloto" para Taller', {
    reply: 'Aplico y apruebo.',
    actions: [
      {
        type: 'create_series_episode', seriesTitle: 'Taller', seriesPremise: '', seriesLogline: '',
        episodeTitle: 'Inventado', episodePremise: 'El hechizo sale mal.', episodeLogline: '',
        genre: '', tone: '', visualStyle: '', worldSummary: '', theme: '', ending: '', language: '',
        characters: [], locations: [], outlineBeats: [], createIfMissing: true, knownUniverse: false,
      },
      { type: 'apply_story_proposal', targetStoryTitle: 'Taller', confirm: true },
      { type: 'commit_series_canon', seriesTitle: 'Taller', targetEpisodeTitle: '', decision: 'accept_all', itemIds: [], confirm: true },
    ],
  })
  assert.deepEqual(stripped.actions.map(action => action.type), ['create_series_episode'])
  assert.equal(stripped.actions[0].episodeTitle, 'Piloto')
  const kept = await reconcileAgentTurnWithRequest('aplica la propuesta de Story Lab', {
    reply: 'La aplico.',
    actions: [{ type: 'apply_story_proposal', targetStoryTitle: 'La torre', confirm: true }],
  })
  assert.deepEqual(kept.actions.map(action => action.type), ['apply_story_proposal'])
})
