import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { installDom } from './seriesInspectorServer'
import { episode, series } from './seriesReviewFixtures'
import { createStoryProject, normalizeStoryProject, changedSections } from '../src/features/stories/model'
import { normalizeSeriesProject } from '../src/features/series/model'
import { applyChanges, catalog, editGuide, guideContext, normalizeGuide, readGuide, undoChanges, type GuideData, type GuidePending } from '../src/features/writing-guide/model'
import { seriesGuideContext } from '../src/features/writing-guide/seriesContext'
import { targetEntity, targetKey, updateTarget } from '../src/features/writing-guide/bindings'

installDom()
const proposal = (base: Record<string, string>): GuidePending => ({
  action: 'develop', questionId: 'desire', base, selected: ['arc'], createdAt: '2026-10-11',
  suggestions: [{ field: 'arc', value: 'Learns to trust', reason: 'A choice resolves the flaw' }], review: [], examples: [],
  usage: null, elapsedSeconds: 1, provider: 'test', model: 'fake',
})

test('manual story answers write canonical fields; extra decisions and proposals survive normalization', () => {
  const original = createStoryProject()
  const target = { scope: 'story' as const, id: original.id }
  const next = updateTarget(original, target, data => ({ ...data, values: { ...data.values, premise: 'A captain loses command', goal: 'Recover the ship' } }))
  assert.equal(next.premise, 'A captain loses command')
  assert.equal(next.writingGuide?.sections['story:root'].notes.goal, 'Recover the ship')
  assert.equal(next.writingGuide?.sections['story:root'].notes.premise, undefined, 'no duplicate canonical answer')
  const withProposal = updateTarget(next, target, data => ({ ...data, section: { ...data.section, pending: { ...proposal(data.values), questionId: 'premise', selected: ['synopsis'], suggestions: [{ field: 'synopsis', value: 'Learns to trust', reason: 'Her choice' }] } } }))
  const restored = normalizeStoryProject(JSON.parse(JSON.stringify(withProposal)))
  assert.equal(restored.writingGuide?.sections['story:root'].pending?.suggestions[0].value, 'Learns to trust')
  assert.deepEqual(changedSections(next, withProposal), [], 'a proposal is not a canon edit')
  assert.ok(changedSections(original, next).includes('overview'))
  assert.equal(original.premise, '', 'source was not mutated')
})

test('a target keeps stable identity across reordering; deleting it does not edit a neighbour', () => {
  const project = series(episode([]))
  const first = project.characters[0]
  project.characters.push({ ...first, id: 'other', name: 'Other' })
  project.characters.reverse()
  const target = { scope: 'seriesCharacter' as const, id: first.id }
  const changed = updateTarget(project, target, data => ({ ...data, values: { ...data.values, desire: 'Return home' } }))
  assert.equal(changed.characters.find(c => c.id === first.id)?.desire, 'Return home')
  assert.equal(changed.characters.find(c => c.id === 'other')?.desire, '')
  assert.equal(changed.canon.approval, 'draft')
  assert.equal(normalizeSeriesProject(JSON.parse(JSON.stringify(changed)))?.characters.find(c => c.id === first.id)?.desire, 'Return home')
  project.characters = project.characters.filter(c => c.id !== first.id)
  assert.equal(updateTarget(project, target, data => ({ ...data, values: { desire: 'wrong' } })), project)
})

test('partial apply and undo protect later manual work', () => {
  let data: GuideData = { values: { desire: 'Ship', need: 'Trust', arc: '' }, section: { notes: {} } }
  const base = { ...data.values }
  data.values.need = 'Share command'
  data = applyChanges(data, base, { arc: 'Learns to trust' })
  assert.equal(data.values.need, 'Share command')
  assert.equal(data.values.arc, 'Learns to trust')
  assert.equal(undoChanges(data).values.arc, '')
  const later = { ...data, values: { ...data.values, arc: 'My manual arc' } }
  assert.equal(undoChanges(later), later)
  assert.equal(applyChanges(later, base, { arc: 'Stale' }), later)
})

test('scene coaching preserves dialogue and shot outputs, and uses episode-qualified identities', () => {
  const project = series(episode([]))
  project.episodesById.ep1.script[0].dialogue = [{ id: 'line1', characterId: project.characters[0].id, text: 'No.', emotion: '', delivery: '' }]
  const target = { scope: 'scene' as const, id: 'scene-1', episodeId: 'ep1' }
  const next = updateTarget(project, target, data => ({ ...data, values: { ...data.values, exitState: 'They agree', beats: 'She gives up the key' } }))
  assert.equal(targetKey(target), 'ep1/scene-1')
  assert.equal(next.episodesById.ep1.script[0].dialogue[0].text, 'No.')
  assert.equal(next.episodesById.ep1.script[0].exitState, 'They agree')
  assert.equal(next.episodesById.ep1.script[0].beats[0].kind, 'action')
  assert.deepEqual(next.episodesById.ep1.shots, project.episodesById.ep1.shots)
  assert.ok(targetEntity(next, target))
})

test('the LLM context excludes credentials, media and unaccepted text', () => {
  const context = guideContext({ premise: 'The port', provider: { api_key: 'SECRET' }, assets: { image: 'data:SECRET' },
    characters: [{ name: 'Ada', voiceProfile: { api_key: 'SECRET' } }] }, { name: 'Ada' },
    { version: 1, sections: { 'character:a': { notes: {}, pending: proposal({ desire: 'SECRET' }) } } })
  assert.ok(JSON.stringify(context).includes('The port'))
  assert.ok(!JSON.stringify(context).includes('SECRET'))
})

test('all catalog fields can round-trip, including newline lists', () => {
  for (const scope of Object.keys(catalog.scopes) as Array<keyof typeof catalog.scopes>) {
    const result = editGuide({}, undefined, scope, 'target', data => ({
      ...data, values: Object.fromEntries(Object.keys(data.values).map(key => [key, 'First\nSecond'])),
    }))
    const data = readGuide(result.entity, result.guide, scope, 'target')
    assert.ok(Object.values(data.values).every(value => value === 'First\nSecond'), scope)
  }
})

test('episode advice sees the frozen world and decisions, without leaking another episode', () => {
  const project = series(episode([]))
  project.canon.worldSummary = 'Changed world'
  project.episodesById.ep1.canonSnapshot = { revision: 1, worldSummary: 'Frozen world',
    writingDecisions: { 'series:root': { engine: 'Frozen engine' } } }
  project.writingGuide = { version: 1, sections: {
    'series:root': { notes: { engine: 'Changed engine' } },
    'episode:ep1': { notes: { goal: 'Save the port' } },
    'episode:other': { notes: { goal: 'PRIVATE OTHER EPISODE' } },
  } }
  const context = seriesGuideContext(project, { scope: 'episode', id: 'ep1' }, project.episodesById.ep1)
  const text = JSON.stringify(context)
  assert.ok(text.includes('Frozen world') && text.includes('Frozen engine') && text.includes('Save the port'))
  assert.ok(!text.includes('Changed world') && !text.includes('Changed engine') && !text.includes('PRIVATE OTHER EPISODE'))
})

test('malformed imported coaching drafts are ignored, while manual notes remain available', () => {
  const normalized = normalizeGuide({ version: 1, sections: { 'story:root': {
    notes: { goal: 'Save the port', bogus: 'wrong' }, pending: { selected: 42 },
  } } })
  assert.deepEqual(normalized.sections['story:root'].notes, { goal: 'Save the port' })
  assert.equal(normalized.sections['story:root'].pending, undefined)
})

test('large narrative context stays bounded without putting output history into the prompt', () => {
  const context = guideContext({ characters: Array.from({ length: 20 }, () => ({
    name: 'Captain', personality: 'x'.repeat(20000), desire: 'y'.repeat(20000), appearance: 'z'.repeat(20000),
  })) }, { title: 'Current' }, undefined)
  assert.ok(JSON.stringify(context).length < 20000)
})

async function mount(t: { after: (fn: () => void) => void }, saved?: GuideData) {
  const { render, cleanup } = await import('@testing-library/react')
  const { WritingGuide } = await import('../src/features/writing-guide/WritingGuide')
  let current = saved || readGuide({ desire: 'Recover the ship', need: 'Trust', flaw: 'Control' }, undefined, 'character', 'captain')
  function Harness() {
    const [data, setData] = useState(current)
    return <WritingGuide scope="character" data={data} language="English" context={{ premise: 'The captain' }}
      provider={{ provider: 'ollama', model: 'fake-model', baseUrl: 'http://localhost:11434' }}
      onChange={update => setData(value => { current = update(value); return current })} />
  }
  const view = render(<Harness />)
  view.getByTestId('writing-guide').setAttribute('open', '')
  t.after(cleanup)
  return { view, data: () => current }
}

test('a late proposal stays editable, blocks stale replacements and accepts selected fresh fields', async t => {
  const { fireEvent, waitFor } = await import('@testing-library/react')
  const original = globalThis.fetch
  let finish: (response: Response) => void = () => {}
  let request: Record<string, unknown> = {}
  globalThis.fetch = (async (_url, init) => {
    request = JSON.parse(String(init?.body))
    return new Promise<Response>(resolve => { finish = resolve })
  }) as typeof fetch
  t.after(() => { globalThis.fetch = original })
  const { view, data } = await mount(t)
  fireEvent.click(view.getByRole('button', { name: 'Develop from my answers' }))
  fireEvent.change(view.getByRole('textbox', { name: /What does this character want/ }), { target: { value: 'Save the crew' } })
  finish(new Response(JSON.stringify({ ...proposal({}), suggestions: [
    { field: 'desire', value: 'Recover the ship at any cost', reason: 'Alternative' },
    { field: 'arc', value: 'Learns to trust', reason: 'Change' },
  ] }), { headers: { 'Content-Type': 'application/json' } }))
  await waitFor(() => assert.ok(view.getByTestId('writing-proposal')))
  assert.equal(request.writingProvider, 'ollama')
  assert.equal(request.writingModel, 'fake-model')
  assert.equal((request.values as Record<string, string>).desire, 'Recover the ship')
  assert.equal(data().values.desire, 'Save the crew')
  fireEvent.click(view.getByRole('checkbox', { name: 'Apply: What does this character want?' }))
  assert.equal((view.getByRole('button', { name: 'Apply selected changes' }) as HTMLButtonElement).disabled, true)
  fireEvent.click(view.getByRole('checkbox', { name: 'Apply: What does this character want?' }))
  fireEvent.change(view.getByRole('textbox', { name: 'Proposal: How do their choices change them?' }), { target: { value: 'Shares command willingly' } })
  fireEvent.click(view.getByRole('button', { name: 'Apply selected changes' }))
  assert.equal(data().values.arc, 'Shares command willingly')
  assert.equal(data().values.desire, 'Save the crew')
  fireEvent.click(view.getByRole('button', { name: 'Undo applied changes' }))
  assert.equal(data().values.arc, '')
})

test('a saved proposal reopens and examples require explicit review before replacing an answer', async t => {
  const { fireEvent, waitFor } = await import('@testing-library/react')
  const base = readGuide({ desire: 'Recover the ship' }, undefined, 'character', 'captain')
  base.section.pending = { ...proposal(base.values), action: 'examples', suggestions: [], selected: [], examples: ['Free the crew', 'Leave the port'] }
  const { view, data } = await mount(t, JSON.parse(JSON.stringify(base)))
  fireEvent.click(view.getAllByRole('button', { name: 'Review this example as a proposal' })[0])
  await waitFor(() => assert.ok(view.getByRole('textbox', { name: 'Proposal: What does this character want?' })))
  assert.equal(data().values.desire, 'Recover the ship')
  assert.equal((view.getByRole('button', { name: 'Apply selected changes' }) as HTMLButtonElement).disabled, true)
  fireEvent.click(view.getByRole('checkbox', { name: 'Apply: What does this character want?' }))
  fireEvent.click(view.getByRole('button', { name: 'Apply selected changes' }))
  assert.equal(data().values.desire, 'Free the crew')
})

test('cancelling a request aborts it and ignores a late response while preserving manual answers', async t => {
  const { fireEvent, act } = await import('@testing-library/react')
  const original = globalThis.fetch
  let finish: (response: Response) => void = () => {}
  let signal: AbortSignal | undefined
  globalThis.fetch = (async (_url, init) => {
    signal = init?.signal as AbortSignal
    return new Promise<Response>(resolve => { finish = resolve })
  }) as typeof fetch
  t.after(() => { globalThis.fetch = original })
  const { view, data } = await mount(t)
  fireEvent.click(view.getByRole('button', { name: 'Examples for my story' }))
  fireEvent.click(view.getByRole('button', { name: 'Cancel', exact: true }))
  assert.equal(signal?.aborted, true)
  await act(async () => { finish(new Response(JSON.stringify({ ...proposal({}), examples: ['Late', 'Ignored'] }))) })
  assert.equal(data().section.pending, undefined)
  assert.equal(data().values.desire, 'Recover the ship')
})

test('guide controls, questions, examples and errors follow the UI language independently of the story', async t => {
  const { fireEvent, waitFor, act } = await import('@testing-library/react')
  const { setUiLanguage } = await import('../src/i18n')
  const original = globalThis.fetch
  let request: Record<string, unknown> = {}
  globalThis.fetch = (async (_url, init) => {
    request = JSON.parse(String(init?.body))
    return new Response(JSON.stringify({ detail: { code: 'invalidProposal', message: 'Invalid writing proposal' } }), { status: 502 })
  }) as typeof fetch
  t.after(() => { globalThis.fetch = original })
  await setUiLanguage('es')
  t.after(() => setUiLanguage('en'))
  const { view } = await mount(t)
  assert.ok(view.getByText('Ayúdame a escribir · Personaje'))
  assert.ok(view.getByRole('textbox', { name: catalog.questions.desire.question.es }))
  assert.ok(view.getByText(`Ejemplo orientativo: ${catalog.questions.desire.example.es}`))
  fireEvent.click(view.getByRole('button', { name: 'Desarrollar con mis respuestas' }))
  await waitFor(() => assert.match(view.getByRole('alert').textContent || '', /formato no válido/))
  assert.equal(request.language, 'English', 'content language stays independent from UI language')
  assert.ok(!view.getByRole('alert').textContent?.includes('Invalid writing proposal'))
  await act(async () => { await setUiLanguage('en') })
  assert.ok(view.getByText('Help me write · Character'))
  assert.match(view.getByRole('alert').textContent || '', /invalid format/)
})

test('unstructured server and network failures use translatable codes, never raw English errors', async t => {
  const { proposeWriting, WritingGuideError } = await import('../src/features/writing-guide/api')
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  const request = { scope: 'story' as const, action: 'develop' as const, questionId: 'premise',
    language: 'English', values: {}, context: {}, provider: { provider: 'maestro', model: '', baseUrl: '' } }
  const signal = new AbortController().signal
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Provider is not configured' }), { status: 503 })
  await assert.rejects(proposeWriting(request, signal), error => error instanceof WritingGuideError && error.code === 'failed')
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(proposeWriting(request, signal), error => error instanceof WritingGuideError && error.code === 'network')
})

test('an unusable writing provider shows the server hint about which setting to fix', async t => {
  const { fireEvent, waitFor } = await import('@testing-library/react')
  const original = globalThis.fetch
  globalThis.fetch = (async () => new Response(JSON.stringify({ detail: { code: 'providerConfig', message: 'Set the Ollama URL in Settings → Services first' } }), { status: 400 })) as typeof fetch
  t.after(() => { globalThis.fetch = original })
  const { view } = await mount(t)
  fireEvent.click(view.getByRole('button', { name: 'Develop from my answers' }))
  await waitFor(() => assert.match(view.getByRole('alert').textContent || '', /Set the Ollama URL in Settings → Services first/))
  assert.match(view.getByRole('alert').textContent || '', /^Set up the writing provider/)
})

test('a long episode keeps the scene context under the server limit without dropping the target', () => {
  const scene = (i: number) => ({ id: `scene-${i}`, purpose: 'p'.repeat(500), entryState: 'e'.repeat(500), exitState: 'x'.repeat(500),
    beats: Array.from({ length: 12 }, (_, j) => ({ id: `b${j}`, kind: 'action', summary: 's'.repeat(500) })),
    dialogue: Array.from({ length: 12 }, (_, j) => ({ id: `l${j}`, characterId: 'c', text: 't'.repeat(500), emotion: 'calm', delivery: 'slow' })) })
  const writingEpisode = { id: 'ep', title: 'Long', premise: 'q'.repeat(500), script: Array.from({ length: 12 }, (_, i) => scene(i)) }
  const characters = Array.from({ length: 12 }, (_, i) => ({ id: `c${i}`, name: `Name ${i}`, desire: 'd'.repeat(500), personality: 'p'.repeat(500) }))
  const context = guideContext({ title: 'Series', writingEpisode, characters }, writingEpisode.script[0], undefined)
  const text = JSON.stringify(context)
  assert.ok(text.length <= 20000, `context is ${text.length} characters`)
  assert.ok(text.includes('scene-0') && text.includes('Name 0'))
})

test('episode advice reads season decisions live while the bible stays frozen', () => {
  const project = series(episode([]))
  project.episodesById.ep1.seasonId = 'season-1'
  project.episodesById.ep1.canonSnapshot = { revision: 1, worldSummary: 'Frozen world',
    writingDecisions: { 'series:root': { engine: 'Frozen engine' }, 'season:season-1': { stakes: 'Frozen season stakes' } } }
  project.writingGuide = { version: 1, sections: {
    'season:season-1': { notes: { stakes: 'Live season stakes' } },
    'season:season-2': { notes: { stakes: 'OTHER SEASON' } },
  } }
  const text = JSON.stringify(seriesGuideContext(project, { scope: 'episode', id: 'ep1' }, project.episodesById.ep1))
  assert.ok(text.includes('Frozen engine') && text.includes('Live season stakes'))
  assert.ok(!text.includes('Frozen season stakes') && !text.includes('OTHER SEASON'))
})
