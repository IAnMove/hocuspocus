import assert from 'node:assert/strict'
import test from 'node:test'
import { CATALOG_VERSION, EXPANDED_CATALOG_VERSION, getCandidateSceneTemplate } from '../src/features/sceneTemplates/catalog.ts'
import { candidateDemoScene } from '../src/features/sceneTemplates/demoScenes.ts'
import {
  loadRenderedReferenceScene,
  parseRenderedReferenceScene,
} from '../src/features/sceneTemplates/previewSnapshot.ts'

const template = getCandidateSceneTemplate('cinema-establishing')
const expected = {
  id: template.id,
  version: template.version,
  catalogVersion: CATALOG_VERSION,
  variant: 'coral',
}

const clone = value => JSON.parse(JSON.stringify(value))

const referenceScene = () => {
  const scene = clone(candidateDemoScene(template.id, expected.variant))
  scene.name = 'Referencia coral guardada'
  scene.duration = 5
  return scene
}

const referencePayload = (scene = referenceScene()) => ({
  catalogVersion: CATALOG_VERSION,
  templateId: template.id,
  templateVersion: template.version,
  variant: expected.variant,
  status: 'rendered-not-approved',
  scene,
})

test('parses the saved coral snapshot instead of recompiling the demo scene', () => {
  const demo = candidateDemoScene(template.id, expected.variant)
  const saved = referenceScene()
  const parsed = parseRenderedReferenceScene(referencePayload(saved), expected)

  assert.deepEqual(parsed, saved)
  assert.notEqual(parsed.name, demo.name)
  assert.equal(parsed.duration, 5)
  assert.equal(parsed.generationPolicy, 'provided_only')
})

test('rejects reference metadata that does not match the requested candidate', () => {
  const cases = [
    ['template id', { templateId: 'music-pulse' }],
    ['template version', { templateVersion: 2 }],
    ['catalog version', { catalogVersion: 'old-catalog' }],
    ['variant', { variant: 'teal' }],
    ['status', { status: 'approved' }],
  ]
  for (const [label, change] of cases) {
    assert.throws(
      () => parseRenderedReferenceScene({ ...referencePayload(), ...change }, expected),
      undefined,
      `${label} mismatch must fail closed`,
    )
  }
})

test('rejects an invalid saved scene even when the outer metadata matches', () => {
  const badPolicy = referenceScene()
  badPolicy.generationPolicy = 'auto'
  assert.throws(() => parseRenderedReferenceScene(referencePayload(badPolicy), expected))

  const badVersion = referenceScene()
  badVersion.version = 2
  assert.throws(() => parseRenderedReferenceScene(referencePayload(badVersion), expected))

  const badLayers = referenceScene()
  badLayers.layers = [{ ...badLayers.layers[0], id: '' }]
  assert.throws(() => parseRenderedReferenceScene(referencePayload(badLayers), expected))

  const mismatchedNarrative = referenceScene()
  mismatchedNarrative.narrative = {
    ...mismatchedNarrative.narrative,
    templateId: 'music-pulse',
  }
  assert.throws(() => parseRenderedReferenceScene(referencePayload(mismatchedNarrative), expected))
})

test('loads the exact reference URL and passes through the caller abort signal', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  const controller = new AbortController()
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), signal: init?.signal })
    return new Response(JSON.stringify(referencePayload()), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    const loaded = await loadRenderedReferenceScene(template, 'http://review.test/scene-template-previews/', controller.signal)
    assert.equal(calls[0].input, 'http://review.test/scene-template-previews/cinema-establishing.json')
    assert.equal(calls[0].signal, controller.signal)
    assert.equal(loaded.name, 'Referencia coral guardada')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('rejects a missing or cancelled reference without falling back to a demo', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response('missing', { status: 404 })
    await assert.rejects(
      loadRenderedReferenceScene(template, 'http://review.test/scene-template-previews'),
    )

    const controller = new AbortController()
    globalThis.fetch = async (_input, init) => {
      assert.equal(init?.signal, controller.signal)
      controller.abort()
      throw new DOMException('The reference request was cancelled.', 'AbortError')
    }
    await assert.rejects(
      loadRenderedReferenceScene(template, 'http://review.test/scene-template-previews', controller.signal),
      error => error?.name === 'AbortError',
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('new music references require their own catalog version without invalidating old references', async () => {
  const music = getCandidateSceneTemplate('music-spiral-exit')
  const scene = candidateDemoScene(music.id)
  const payload = { catalogVersion: EXPANDED_CATALOG_VERSION, templateId: music.id,
    templateVersion: 1, variant: 'coral', status: 'rendered-not-approved', scene }
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response(JSON.stringify(payload))
    assert.deepEqual(await loadRenderedReferenceScene(music, '/scene-template-previews'), scene)
    globalThis.fetch = async () => new Response(JSON.stringify({ ...payload, catalogVersion: CATALOG_VERSION }))
    await assert.rejects(loadRenderedReferenceScene(music, '/scene-template-previews'), /identity|version/i)
    assert.deepEqual(parseRenderedReferenceScene(referencePayload(), expected), referenceScene())
  } finally { globalThis.fetch = originalFetch }
})
