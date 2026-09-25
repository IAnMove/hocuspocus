import assert from 'node:assert/strict'
import test from 'node:test'
import type { AssetCatalogItem } from '../src/api/assets.ts'
import type { ApiOutput } from '../src/api/outputs.ts'
import {
  catalogItemToOutput,
  catalogItemToPickerItem,
  matchCatalogByOutput,
  voiceRefFromOutput,
  checkCompatibility,
  confirmPickerChoice,
  createCatalogQuerySession,
  filterPickerItems,
  isSameRef,
  livePickerItem,
  matchOutputByPicker,
  outputToPickerItem,
  pickerItemToOutput,
  queryAssetCatalog,
  resolveAssetRef,
  sortPickerItems,
  type AssetPickerIntent,
  type PickerItem,
} from '../src/features/asset-picker/index.ts'

function catalogItem(overrides: Partial<AssetCatalogItem> & Pick<AssetCatalogItem, 'id' | 'filename'>): AssetCatalogItem {
  return {
    kind: 'image',
    size_bytes: 12,
    created_at: 1_700_000_000,
    completed_at: 1_700_000_100,
    metadata_status: 'canonical',
    workspace_ids: ['default'],
    locations: [{ workspace_id: 'default', filename: overrides.filename, url: `/api/v1/file/${overrides.filename}` }],
    url: `/api/v1/file/${overrides.filename}`,
    origin: { tool: 'studio' },
    execution: {},
    model: {},
    prompt_preview: '',
    ...overrides,
  }
}

test('catalog and legacy images use bounded thumbnails, preserving originals only for explicit preview', () => {
  const item = catalogItem({ id: 'large', filename: 'large image.png' })
  const picked = catalogItemToPickerItem(item, 'default')
  assert.equal(picked.url, item.url)
  assert.equal(picked.thumbnailUrl, '/api/v1/outputs/thumbnail/large%20image.png?workspace=default&size=sm')
  const output = catalogItemToOutput(item, 'default')!
  assert.equal(output.thumbnail_url, picked.thumbnailUrl)
  const legacy = outputToPickerItem({ ...output, thumbnail_url: item.url }, 'default')
  assert.equal(legacy.thumbnailUrl, picked.thumbnailUrl)
})

test('voice refs keep the uploads/audio subfolder the backend can resolve', () => {
  const uploaded = voiceRefFromOutput({
    name: '9f2.wav',
    type: 'audio',
    mode: null,
    size: 12,
    created_at: 1,
    url: '/api/v1/uploads/audio/9f2.wav',
    thumbnail_url: '',
  }, 'default')
  assert.deepEqual(uploaded, { filename: '9f2.wav', path: 'audio/9f2.wav' })

  const library = voiceRefFromOutput({
    name: 'hero.wav',
    type: 'audio',
    mode: null,
    size: 12,
    created_at: 1,
    url: '/api/v1/file/hero.wav?workspace=default',
    thumbnail_url: '',
  }, 'default')
  assert.deepEqual(library, { filename: 'hero.wav', path: 'hero.wav' })

  const videoUpload = voiceRefFromOutput({
    name: 'take.mp4',
    type: 'video',
    mode: null,
    size: 12,
    created_at: 1,
    url: '/api/v1/uploads/take.mp4',
    thumbnail_url: '',
  }, 'default')
  assert.deepEqual(videoUpload, { filename: 'take.mp4', path: 'take.mp4' })
})

test('catalog items map to outputs and match back by id', () => {
  const item = catalogItem({ id: 'asset-hero', filename: 'hero.png' })
  const output = catalogItemToOutput(item, 'default')
  assert.ok(output)
  assert.equal(output?.name, 'hero.png')
  assert.equal(output?.type, 'image')
  assert.equal(output?.url, '/api/v1/file/hero.png')
  assert.equal(output?.asset_id, 'asset-hero')
  assert.equal(output?.workspace_id, 'default')
  assert.equal(matchCatalogByOutput([item], output!, 'default')?.id, 'asset-hero')
  const picker = outputToPickerItem(output!, 'default')
  assert.equal(picker.ref.scheme, 'catalog')
  if (picker.ref.scheme === 'catalog') assert.equal(picker.ref.id, 'asset-hero')
  const roundTrip = pickerItemToOutput(picker)
  assert.equal(roundTrip?.asset_id, 'asset-hero')
  assert.equal(roundTrip?.workspace_id, 'default')
  assert.equal(roundTrip?.name, 'hero.png')
})

test('homonymous catalog files are not matched by filename alone', () => {
  const alpha = catalogItem({
    id: 'asset-alpha', filename: 'same.png', workspace_ids: ['alpha'],
    locations: [{ workspace_id: 'alpha', filename: 'same.png', url: '/api/v1/file/same.png?workspace=alpha' }],
    url: '/api/v1/file/same.png?workspace=alpha',
  })
  const beta = catalogItem({
    id: 'asset-beta', filename: 'same.png', workspace_ids: ['beta'],
    locations: [{ workspace_id: 'beta', filename: 'same.png', url: '/api/v1/file/same.png?workspace=beta' }],
    url: '/api/v1/file/same.png?workspace=beta',
  })
  const byNameOnly: ApiOutput = {
    name: 'same.png', type: 'image', mode: null, size: 12, created_at: 1,
    url: '/api/v1/file/same.png?workspace=beta',
  }
  assert.equal(matchCatalogByOutput([alpha, beta], byNameOnly, 'default'), undefined)
  const chosen = catalogItemToOutput(beta, 'beta')
  assert.equal(matchCatalogByOutput([alpha, beta], chosen!, 'beta')?.id, 'asset-beta')
})

test('homonymous files in different workspaces keep distinct refs', () => {
  const alpha = catalogItemToPickerItem(catalogItem({
    id: 'asset_alpha', filename: 'same.png',
    workspace_ids: ['alpha'],
    locations: [{ workspace_id: 'alpha', filename: 'same.png', url: '/api/v1/file/same.png?workspace=alpha' }],
  }), 'alpha')
  const beta = catalogItemToPickerItem(catalogItem({
    id: 'asset_beta', filename: 'same.png',
    workspace_ids: ['beta'],
    locations: [{ workspace_id: 'beta', filename: 'same.png', url: '/api/v1/file/same.png?workspace=beta' }],
  }), 'beta')
  assert.equal(alpha.filename, beta.filename)
  assert.equal(isSameRef(alpha.ref, beta.ref), false)
  assert.equal(alpha.ref.scheme, 'catalog')
  if (alpha.ref.scheme === 'catalog' && beta.ref.scheme === 'catalog') {
    assert.notEqual(alpha.ref.id, beta.ref.id)
  }
})

test('missing created_at becomes unknown date, not completed_at', async () => {
  const { formatCreatedDate, formatUnknownDate } = await import('../src/features/asset-picker/titles.ts')
  const item = catalogItemToPickerItem(catalogItem({
    id: 'asset_old', filename: 'old.png', created_at: 0, completed_at: 9_999,
  }), 'default')
  assert.equal(item.createdAt, null)
  assert.equal(formatCreatedDate(item.createdAt), formatUnknownDate())
  assert.match(item.title, /Unknown date|Fecha desconocida/)
})

test('legacy outputs do not invent catalog ids', () => {
  const output: ApiOutput = {
    name: 'hero.glb', type: 'model3d', mode: null, size: 4, created_at: 12,
    url: '/api/v1/file/hero.glb', thumbnail_url: '/api/v1/file/hero.png',
  }
  const item = outputToPickerItem(output, 'film')
  assert.equal(item.ref.scheme, 'legacy-output')
  if (item.ref.scheme === 'legacy-output') {
    assert.equal(item.ref.filename, 'hero.glb')
    assert.equal(item.ref.workspaceId, 'film')
  }
  assert.equal(item.kind, 'model3d')
})

test('cancel, clear and confirm are distinct intents', () => {
  const cancel: AssetPickerIntent = { type: 'cancel' }
  const clear: AssetPickerIntent = { type: 'clear' }
  const confirm: AssetPickerIntent = { type: 'confirm', items: [] }
  assert.notEqual(cancel.type, clear.type)
  assert.notEqual(clear.type, confirm.type)
})

test('constraints reject incompatible kinds and overflow', () => {
  const item = catalogItemToPickerItem(catalogItem({ id: 'a', filename: 'a.png' }), 'default')
  assert.equal(checkCompatibility(item, { kinds: ['audio'], maxCount: 1, optional: true }, 0).allowed, false)
  assert.equal(checkCompatibility(item, { kinds: ['image'], maxCount: 1, optional: false }, 1).allowed, false)
  assert.equal(checkCompatibility(item, { kinds: ['image'], maxCount: 1, optional: false }, 0).allowed, true)
})

test('client sort keeps missing dates last and prefix names in reverse', () => {
  const items: PickerItem[] = [
    catalogItemToPickerItem(catalogItem({ id: 'a', filename: 'a.png', created_at: 10 }), 'default'),
    catalogItemToPickerItem(catalogItem({ id: 'ab', filename: 'ab.png', created_at: 30 }), 'default'),
    catalogItemToPickerItem(catalogItem({ id: 'b', filename: 'b.png', created_at: 0 }), 'default'),
  ]
  assert.deepEqual(sortPickerItems(items, 'created_desc').map(item => item.filename), ['ab.png', 'a.png', 'b.png'])
  assert.deepEqual(sortPickerItems(items, 'name_desc').map(item => item.filename), ['b.png', 'ab.png', 'a.png'])
  assert.deepEqual(filterPickerItems(items, 'ab').map(item => item.filename), ['ab.png'])
})

test('query session ignores an out-of-order response', async () => {
  const originalFetch = globalThis.fetch
  let resolveFirst: ((value: Response) => void) | undefined
  const first = new Promise<Response>(resolve => { resolveFirst = resolve })
  let calls = 0
  globalThis.fetch = (async () => {
    calls += 1
    if (calls === 1) return first
    return new Response(JSON.stringify({
      total: 1,
      assets: [catalogItem({ id: 'second', filename: 'second.png' })],
    }))
  }) as typeof fetch
  try {
    const session = createCatalogQuerySession()
    const pending = session.run({ workspace: 'default' })
    const latest = session.run({ workspace: 'default' })
    resolveFirst?.(new Response(JSON.stringify({
      total: 1,
      assets: [catalogItem({ id: 'first', filename: 'first.png' })],
    })))
    const stale = await pending
    const fresh = await latest
    assert.equal(stale.stale, true)
    assert.equal(fresh.stale, false)
    assert.equal(fresh.items[0]?.filename, 'second.png')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('resolveAssetRef reports 404 for an unknown catalog id', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => new Response('missing', { status: 404 })) as typeof fetch
  try {
    await assert.rejects(
      () => resolveAssetRef({ version: 1, scheme: 'catalog', id: 'nope', workspaceId: 'default', filename: 'nope.png' }),
      (error: unknown) => error instanceof Error
        && error.message === 'Asset not found'
        && (error as Error & { status?: number }).status === 404,
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('strict catalog mapping does not fall back to another workspace', () => {
  const item = catalogItem({
    id: 'shared', filename: 'same.png',
    workspace_ids: ['alpha', 'beta'],
    locations: [
      { workspace_id: 'alpha', filename: 'same.png', url: '/alpha/same.png' },
      { workspace_id: 'beta', filename: 'same.png', url: '/beta/same.png' },
    ],
  })
  const browse = catalogItemToPickerItem(item, 'missing')
  assert.equal(browse.url, '/alpha/same.png')
  assert.throws(
    () => catalogItemToPickerItem(item, 'missing', { strict: true }),
    (error: unknown) => error instanceof Error
      && error.message === 'Asset location not found'
      && (error as Error & { status?: number }).status === 409,
  )
})

test('resolveAssetRef pages past the first fifty search-like hits', async () => {
  const originalFetch = globalThis.fetch
  const decoys = Array.from({ length: 50 }, (_, index) => catalogItem({
    id: `decoy_${index}`, filename: `hit-${index}.png`,
    prompt_preview: 'wanted.png',
    locations: [{ workspace_id: 'film', filename: `hit-${index}.png`, url: `/d/${index}` }],
    workspace_ids: ['film'],
  }))
  const wanted = catalogItem({
    id: 'wanted', filename: 'wanted.png',
    locations: [{ workspace_id: 'film', filename: 'wanted.png', url: '/wanted.png' }],
    workspace_ids: ['film'],
  })
  globalThis.fetch = (async (url: RequestInfo | URL) => {
    const parsed = new URL(String(url), 'http://localhost')
    const offset = Number(parsed.searchParams.get('offset') || '0')
    const limit = Number(parsed.searchParams.get('limit') || '50')
    const all = [...decoys, wanted]
    return new Response(JSON.stringify({
      total: all.length,
      assets: all.slice(offset, offset + limit),
    }))
  }) as typeof fetch
  try {
    const match = await resolveAssetRef({
      version: 1, scheme: 'legacy-output', workspaceId: 'film', filename: 'wanted.png', outputType: 'image',
    })
    assert.equal(match.id, 'wanted')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('catalog resolve refuses a silent workspace substitution', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => new Response(JSON.stringify(catalogItem({
    id: 'asset_alpha', filename: 'same.png', workspace_ids: ['alpha'],
    locations: [{ workspace_id: 'alpha', filename: 'same.png', url: '/alpha' }],
  })))) as typeof fetch
  try {
    await assert.rejects(
      () => resolveAssetRef({
        version: 1, scheme: 'catalog', id: 'asset_alpha', workspaceId: 'beta', filename: 'same.png',
      }),
      (error: unknown) => error instanceof Error
        && error.message === 'Asset location not found'
        && (error as Error & { status?: number }).status === 409,
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('query session dispose aborts the in-flight request', async () => {
  const originalFetch = globalThis.fetch
  const session = createCatalogQuerySession()
  let aborted = false
  globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
    await new Promise<void>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => {
        aborted = true
        reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
      })
    })
    return new Response(JSON.stringify({ total: 0, assets: [] }))
  }) as typeof fetch
  try {
    const pending = session.run({ workspace: 'default' })
    session.dispose()
    const result = await pending
    assert.equal(aborted, true)
    assert.equal(result.stale, true)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('legacy resolve keeps homonyms distinct by workspace', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => new Response(JSON.stringify({
    total: 2,
    assets: [
      catalogItem({
        id: 'asset_alpha', filename: 'same.png', workspace_ids: ['alpha'],
        locations: [{ workspace_id: 'alpha', filename: 'same.png', url: '/a' }],
      }),
      catalogItem({
        id: 'asset_beta', filename: 'same.png', workspace_ids: ['beta'],
        locations: [{ workspace_id: 'beta', filename: 'same.png', url: '/b' }],
      }),
    ],
  }))) as typeof fetch
  try {
    const match = await resolveAssetRef({
      version: 1, scheme: 'legacy-output', workspaceId: 'beta', filename: 'same.png', outputType: 'image',
    })
    assert.equal(match.id, 'asset_beta')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('confirm resolves by full ref and url, not filename', () => {
  const twins: ApiOutput[] = [
    { name: 'same.glb', type: 'model3d', mode: null, size: 1, created_at: 1, url: '/api/v1/file/a/same.glb', thumbnail_url: '/a.png' },
    { name: 'same.glb', type: 'model3d', mode: null, size: 2, created_at: 2, url: '/api/v1/file/b/same.glb', thumbnail_url: '/b.png' },
  ]
  const items = twins.map(item => outputToPickerItem(item, 'film'))
  const chosen: string[] = []
  const ok = confirmPickerChoice(twins, items, items[1], 'film', undefined, item => { if (item) chosen.push(item.url) }, () => undefined)
  assert.equal(ok, true)
  assert.deepEqual(chosen, ['/api/v1/file/b/same.glb'])
  assert.equal(matchOutputByPicker(twins, items[0], 'film')?.url, '/api/v1/file/a/same.glb')
  assert.equal(livePickerItem(items.slice(1), items[0]), null)
})

test('confirm refuses a live item that is gone or incompatible', () => {
  const output: ApiOutput = {
    name: 'plate.png', type: 'image', mode: null, size: 2, created_at: 1,
    url: '/api/v1/file/plate.png', thumbnail_url: '/api/v1/file/plate.png',
  }
  const item = outputToPickerItem(output, 'film')
  const chosen: Array<string | null> = []
  assert.equal(confirmPickerChoice([], [item], item, 'film', undefined, value => chosen.push(value ? value.name : null), () => undefined), false)
  assert.deepEqual(chosen, [])
  assert.equal(confirmPickerChoice(
    [output], [item], item, 'film',
    { kinds: ['audio'], maxCount: 1, optional: false },
    value => chosen.push(value ? value.name : null),
    () => undefined,
  ), false)
  assert.deepEqual(chosen, [])
})

test('picker catalog queries default to created_desc and 24 items', async () => {
  const originalFetch = globalThis.fetch
  const calls: string[] = []
  globalThis.fetch = (async (url: RequestInfo | URL) => {
    calls.push(String(url))
    return new Response(JSON.stringify({ total: 0, assets: [] }))
  }) as typeof fetch
  try {
    await queryAssetCatalog({ workspace: 'default' })
    const url = new URL(calls[0], 'http://localhost')
    assert.equal(url.searchParams.get('sort'), 'created_desc')
    assert.equal(url.searchParams.get('limit'), '24')
    assert.equal(url.searchParams.get('workspace'), 'default')
  } finally {
    globalThis.fetch = originalFetch
  }
})
