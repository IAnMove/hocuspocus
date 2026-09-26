import assert from 'node:assert/strict'
import test from 'node:test'
import { getCandidateSceneTemplate } from '../src/features/sceneTemplates/catalog.ts'
import {
  catalogAssetBinding,
  catalogBindingIssue,
  resolveCatalogBindings,
} from '../src/features/sceneTemplates/catalogBindings.ts'
import { compileCandidateScene } from '../src/features/sceneTemplates/compile.ts'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile.ts'

const WORKSPACE = 'default'
const template = getCandidateSceneTemplate('cinema-establishing')
const imageSlot = template.slots.find(slot => slot.id === 'hero')
const plateSlot = template.slots.find(slot => slot.id === 'plate')
const modelTemplate = getCandidateSceneTemplate('space-cruise')
const modelSlot = modelTemplate.slots.find(slot => slot.id === 'hero')
assert.ok(imageSlot)
assert.ok(plateSlot)
assert.ok(modelSlot)

const makeAsset = (overrides = {}) => ({
  id: 'asset-hero', kind: 'image', filename: 'hero.png', size_bytes: 12,
  created_at: 1, completed_at: 2, metadata_status: 'canonical', workspace_ids: [WORKSPACE],
  locations: [{ workspace_id: WORKSPACE, filename: 'hero.png', url: '/api/v1/file/hero.png?workspace=default' }],
  // This field must never be used instead of the active-workspace location.
  url: '/api/v1/file/hero.png?workspace=default',
  origin: { tool: 'catalog-test' }, execution: { run_id: 'run-1', task_id: 'task-1' },
  model: { provider: 'local', id: 'fixture-model' }, prompt_preview: 'hero',
  ...overrides,
})

const responseFor = value => new Response(JSON.stringify(value), {
  status: 200,
  headers: { 'content-type': 'application/json' },
})

test('accepts the canonical active-workspace location, not a global asset URL', () => {
  const item = makeAsset({ url: 'https://untrusted.example/old/hero.png' })
  const binding = catalogAssetBinding(item, WORKSPACE, imageSlot)

  assert.equal(binding.source, '/api/v1/file/hero.png?workspace=default')
  assert.equal(binding.type, 'image')
  assert.equal(binding.catalogAtAssignment.assetId, item.id)
  assert.equal(binding.catalogAtAssignment.workspaceId, WORKSPACE)
  assert.equal(binding.catalogAtAssignment.metadataStatus, 'canonical')
  assert.equal(binding.catalogAtAssignment.originTool, 'catalog-test')
})

test('blocks non-canonical metadata and unsafe, ambiguous, or incompatible locations', () => {
  for (const metadata_status of ['legacy', 'missing', 'invalid']) {
    const item = makeAsset({ metadata_status })
    assert.throws(() => catalogAssetBinding(item, WORKSPACE, imageSlot), /canonical Library identity and metadata/i)
    assert.match(catalogBindingIssue(item, WORKSPACE, imageSlot), /canonical Library identity and metadata/i)
  }

  const cases = [
    ['remote source', { locations: [{ workspace_id: WORKSPACE, filename: 'hero.png', url: 'https://evil.example/hero.png' }] }],
    ['blob source', { locations: [{ workspace_id: WORKSPACE, filename: 'hero.png', url: 'blob:http://localhost/temporary' }] }],
    ['wrong workspace', { locations: [{ workspace_id: 'other', filename: 'hero.png', url: '/api/v1/file/hero.png?workspace=other' }] }],
    ['ambiguous locations', { locations: [
      { workspace_id: WORKSPACE, filename: 'hero.png', url: '/api/v1/file/hero.png?workspace=default' },
      { workspace_id: WORKSPACE, filename: 'hero-2.png', url: '/api/v1/file/hero-2.png?workspace=default' },
    ] }],
    ['wrong type', { kind: 'model3d' }],
  ]
  for (const [label, overrides] of cases) {
    assert.throws(
      () => catalogAssetBinding(makeAsset(overrides), WORKSPACE, imageSlot),
      undefined,
      `${label} must be rejected`,
    )
  }

  const nonGlb = makeAsset({
    id: 'ship', kind: 'model3d', filename: 'ship.obj',
    workspace_ids: [WORKSPACE],
    locations: [{ workspace_id: WORKSPACE, filename: 'ship.obj', url: '/api/v1/file/ship.obj?workspace=default' }],
    url: '/api/v1/file/ship.obj?workspace=default',
  })
  assert.throws(() => catalogAssetBinding(nonGlb, WORKSPACE, modelSlot), /GLB/i)
})

test('matches Python quote for parentheses, quotes, punctuation and Unicode in names/workspaces', () => {
  const workspace = "film(2)!'"
  const filename = "héro(1)!'*.png"
  const source = '/api/v1/file/h%C3%A9ro%281%29%21%27%2A.png?workspace=film%282%29%21%27'
  const item = makeAsset({ filename, locations: [{ workspace_id: workspace, filename, url: source }] })
  const binding = catalogAssetBinding(item, workspace, imageSlot)
  assert.equal(binding.source, source)
  assert.equal(binding.catalogAtAssignment.filename, filename)
  assert.equal(binding.catalogAtAssignment.workspaceId, workspace)
})

test('re-resolves by durable id and rejects identity, type, or source changes', async () => {
  const selected = makeAsset({ id: 'asset-selected' })
  const selectedPlate = makeAsset({
    id: 'asset-plate', filename: 'plate.png',
    locations: [{ workspace_id: WORKSPACE, filename: 'plate.png', url: '/api/v1/file/plate.png?workspace=default' }],
    url: '/api/v1/file/plate.png?workspace=default',
  })
  const selections = { hero: selected, plate: selectedPlate }
  const originalFetch = globalThis.fetch
  const calls = []
  try {
    globalThis.fetch = async (input, init) => {
      calls.push({ input: String(input), signal: init?.signal })
      const id = decodeURIComponent(String(input).split('/').pop())
      return responseFor(id === selected.id ? selected : selectedPlate)
    }
    const bindings = await resolveCatalogBindings(template, selections, WORKSPACE, new AbortController().signal)
    assert.deepEqual(bindings.hero.source, selected.locations[0].url)
    assert.deepEqual(bindings.plate.source, selectedPlate.locations[0].url)
    assert.deepEqual(calls.map(call => call.input), [
      '/api/v1/assets/asset-selected',
      '/api/v1/assets/asset-plate',
    ])
    assert.ok(calls.every(call => call.signal instanceof AbortSignal))

    const assertChanged = async (changed, message) => {
      globalThis.fetch = async () => responseFor(changed)
      await assert.rejects(
        resolveCatalogBindings(template, selections, WORKSPACE, new AbortController().signal),
        undefined,
        message,
      )
    }
    await assertChanged({ ...selected, id: 'asset-replaced' }, 'changed id must fail')
    await assertChanged({ ...selected, kind: 'model3d' }, 'changed kind must fail')
    await assertChanged({
      ...selected,
      locations: [{ workspace_id: WORKSPACE, filename: 'new-hero.png', url: '/api/v1/file/new-hero.png?workspace=default' }],
      url: '/api/v1/file/new-hero.png?workspace=default',
    }, 'changed source must fail')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('abort and 404 fail closed without invoking a generator endpoint', async () => {
  const selected = makeAsset({ id: 'asset-abort' })
  const originalFetch = globalThis.fetch
  const calls = []
  try {
    const controller = new AbortController()
    globalThis.fetch = async (input, init) => {
      calls.push({ input: String(input), signal: init?.signal })
      if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      return new Response('missing', { status: 404 })
    }
    controller.abort()
    await assert.rejects(resolveCatalogBindings(template, { hero: selected }, WORKSPACE, controller.signal), /Abort/i)
    await assert.rejects(resolveCatalogBindings(template, { hero: selected }, WORKSPACE, new AbortController().signal), /Asset not found/i)
    assert.ok(calls.every(call => call.input.includes('/api/v1/assets/')))
    assert.equal(calls.some(call => /generate|model3d/i.test(call.input)), false)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('compile, serialize, and parse preserve catalog references without shared mutation', () => {
  const hero = makeAsset({ id: 'asset-hero-roundtrip' })
  const plate = makeAsset({
    id: 'asset-plate-roundtrip', filename: 'plate.png',
    locations: [{ workspace_id: WORKSPACE, filename: 'plate.png', url: '/api/v1/file/plate.png?workspace=default' }],
    url: '/api/v1/file/plate.png?workspace=default',
  })
  const bindings = {
    hero: catalogAssetBinding(hero, WORKSPACE, imageSlot),
    plate: catalogAssetBinding(plate, WORKSPACE, plateSlot),
  }
  const scene = compileCandidateScene(template.id, bindings)
  const json = serializeSceneFile(scene)
  const parsed = parseSceneFile(json)
  const originalAssets = scene.narrative.assets
  const parsedAssets = parsed.narrative.assets

  assert.deepEqual(parsedAssets, originalAssets)
  assert.notEqual(parsedAssets, originalAssets)
  assert.notEqual(parsedAssets[0].catalogAtAssignment, originalAssets[0].catalogAtAssignment)
  parsedAssets[0].catalogAtAssignment.assetId = 'mutated-after-parse'
  assert.equal(originalAssets[0].catalogAtAssignment.assetId, 'asset-hero-roundtrip')
  assert.equal(bindings.hero.catalogAtAssignment.assetId, 'asset-hero-roundtrip')
})
