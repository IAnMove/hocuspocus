import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body><div id="story-review-world"></div></body></html>', {
  url: 'http://localhost/',
})
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
  HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
})
window.matchMedia = () => ({ matches: false })
window.HTMLElement.prototype.scrollIntoView = () => undefined

test('Story Lab navigation keeps aliases and never claims an invisible tab opened', async () => {
  const {
    canonicalizeStoryLabSection,
    resolveStoryLabNavigation,
    describeStoryLabNavigation,
  } = await import('../src/features/stories/labNavigation.ts')

  assert.equal(canonicalizeStoryLabSection('song'), 'music')
  assert.equal(canonicalizeStoryLabSection('generate'), 'productions')
  assert.equal(canonicalizeStoryLabSection('images'), 'assets')

  const fullWorld = resolveStoryLabNavigation('world', 'full_story')
  assert.equal(fullWorld.ok, true)
  assert.equal(fullWorld.tab, 'world')
  assert.equal(fullWorld.equivalent, false)

  const musicWorld = resolveStoryLabNavigation('world', 'music_video')
  assert.equal(musicWorld.ok, true)
  assert.equal(musicWorld.tab, 'overview')
  assert.equal(musicWorld.anchor, 'story-review-world')
  assert.equal(musicWorld.equivalent, true)
  assert.match(describeStoryLabNavigation(musicWorld), /overview/)
  assert.doesNotMatch(describeStoryLabNavigation(musicWorld), /Story Lab → world\.$/)

  const trailerMusic = resolveStoryLabNavigation('music', 'trailer')
  assert.equal(trailerMusic.ok, false)
  assert.match(trailerMusic.reason, /is not visible/)

  const trailerProductions = resolveStoryLabNavigation('productions', 'trailer')
  assert.equal(trailerProductions.ok, true)
  assert.equal(trailerProductions.tab, 'trailer')

  const fullCharacters = resolveStoryLabNavigation('characters', 'full_story')
  assert.equal(fullCharacters.ok, true)
  assert.equal(fullCharacters.tab, 'world')
  assert.equal(fullCharacters.equivalent, true)
  assert.equal(fullCharacters.anchor, 'story-review-characters')
})

test('open_story_section reports the resolved destination for compact Story types', async () => {
  const { registerNavigationQueueCapabilities } = await import('../src/features/agent/navigationQueueCapabilities.ts')
  const { useStoryStore, createStoryProject } = await import('../src/features/stories/store.ts')
  const definitions = new Map()
  registerNavigationQueueCapabilities(definition => {
    definitions.set(definition.name, definition)
    return definition
  })
  const musicVideo = createStoryProject('music_video')
  useStoryStore.setState({ project: musicVideo, projects: { [musicVideo.id]: musicVideo } })
  const adapters = {
    storyLab: {
      async open() {
        return { message: 'Opened', target: { kind: 'application_section', id: 'story_lab', title: 'Story Lab' } }
      },
    },
  }
  const outcome = await definitions.get('open_story_section').execute(
    { type: 'open_story_section', section: 'world' },
    { adapters },
  )
  assert.match(outcome.message, /overview/)
  assert.doesNotMatch(outcome.message, /Story Lab → world\.$/)

  const trailer = createStoryProject('trailer')
  useStoryStore.setState({ project: trailer, projects: { [trailer.id]: trailer } })
  await assert.rejects(
    () => definitions.get('open_story_section').execute(
      { type: 'open_story_section', section: 'music' },
      { adapters },
    ),
    /is not visible/,
  )
})

test('presentation replay can follow Story review ids without failing the command', async () => {
  const { replayWizardPresentation } = await import('../src/features/agent/wizardPresentation.ts')
  const status = await replayWizardPresentation({
    anchors: ['story-review-world'],
    speed: 'instant',
    replay: 'atomic',
  })
  assert.equal(status, 'replayed')
  const missing = await replayWizardPresentation({
    anchors: ['story-review-missing'],
    speed: 'instant',
    replay: 'atomic',
  })
  assert.equal(missing, 'skipped')
})
