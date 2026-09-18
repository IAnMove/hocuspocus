import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { defaultSpeech } from '../src/features/scene3d/speech/types'
import { clearModelDigestCache, hashSha256, loadFaceProfile, modelDigest, saveFaceProfile, sha256Hex, storedGlbTarget } from '../src/features/scene3d/speech/profiles'

const face = { meshIndex: 0, center: [0, 1.5, .1], size: [.1, .08], skin: [.5, .3, .2],
  eyes: { left: [-.04, 1.55, .1], right: [.04, 1.55, .1], size: [.04, .02], skinLeft: [.5, .3, .2], skinRight: [.5, .3, .2] } }
const speech = () => ({ ...defaultSpeech(), face })
const HEX = 'a'.repeat(64)

test.afterEach(() => { clearModelDigestCache() })

test('LAN fallback SHA-256 matches WebCrypto and Node for the same bytes', async () => {
  const bytes = new TextEncoder().encode('same GLB bytes')
  const node = createHash('sha256').update(bytes).digest('hex')
  assert.equal(sha256Hex(bytes), node)
  assert.equal(sha256Hex(new Uint8Array()), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
  assert.equal(await hashSha256(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)), node)
  const original = globalThis.crypto
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {} })
  try { assert.equal(await hashSha256(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)), node) }
  finally { Object.defineProperty(globalThis, 'crypto', { configurable: true, value: original }) }
})

test('stored GLB identity prefers the workspace SHA-256, not the filename or host', async () => {
  assert.deepEqual(storedGlbTarget('http://192.168.1.87:42007/api/v1/file/mira.glb?workspace=one'), { workspace: 'one', filename: 'mira.glb' })
  assert.deepEqual(storedGlbTarget('http://localhost:42007/api/v1/file/mira.glb?workspace=one'), { workspace: 'one', filename: 'mira.glb' })
  assert.equal(storedGlbTarget('/test/mira.glb'), undefined)
  const original = globalThis.fetch
  const seen: string[] = []
  globalThis.fetch = async (url) => {
    seen.push(String(url))
    if (String(url).includes('/speech/digest')) return Response.json({ digest: HEX, bytes: 12 })
    return new Response('should-not-hash')
  }
  try {
    assert.equal(await modelDigest('http://192.168.1.87:42007/api/v1/file/mira.glb?workspace=one', 'one'), HEX)
    assert.equal(await modelDigest('http://localhost:42007/api/v1/file/mira.glb?workspace=one', 'one'), HEX)
    assert.ok(seen.every(value => value.includes('/speech/digest') && value.includes('filename=mira.glb')))
    assert.ok(!seen.some(value => value.includes('192.168') || value.includes('localhost:42007/api/v1/file/')))
  } finally { globalThis.fetch = original }
})

test('content-addressed fallback never uses the filename when the digest route is absent', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async (url) => {
    if (String(url).includes('/speech/digest')) return new Response('missing', { status: 404 })
    return new Response(String(url).includes('other') ? 'other GLB bytes' : 'same GLB bytes')
  }
  try {
    const a = await modelDigest('/api/v1/file/mira-a.glb?workspace=one', 'one')
    const b = await modelDigest('/api/v1/file/mira-b.glb?workspace=one', 'one')
    const c = await modelDigest('/api/v1/file/other.glb?workspace=one', 'one')
    assert.match(a, /^[a-f0-9]{64}$/)
    assert.equal(a, b)
    assert.notEqual(a, c)
    assert.notEqual(a, 'mira-a.glb')
  } finally { globalThis.fetch = original }
})

test('non-subtle hash is kept only when it matches the stored server digest', async () => {
  const originalCrypto = globalThis.crypto, originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: {} })
  let digestCalls = 0
  globalThis.fetch = async (url) => {
    if (String(url).includes('/speech/digest')) {
      digestCalls++
      if (digestCalls === 1) return new Response('missing', { status: 404 })
      return Response.json({ digest: HEX, bytes: 4 })
    }
    return new Response('same GLB bytes')
  }
  try {
    await assert.rejects(() => modelDigest('/api/v1/file/mira.glb?workspace=one', 'one'), /mismatch/)
    assert.equal(digestCalls, 2)
  } finally {
    Object.defineProperty(globalThis, 'crypto', { configurable: true, value: originalCrypto })
    globalThis.fetch = originalFetch
  }
})

test('oversized models, aborted character changes and revision conflicts do not clobber calibration', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => new Response('glb', { headers: { 'content-length': String(65 * 1024 * 1024) } })
  try { await assert.rejects(() => modelDigest('/models/too-big.glb'), /64 MB/) }
  finally { globalThis.fetch = original }

  const controller = new AbortController()
  globalThis.fetch = async () => new Promise((_, reject) => { controller.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))) })
  const pending = modelDigest('/late.glb', 'one', controller.signal)
  controller.abort()
  await assert.rejects(() => pending, /aborted|AbortError/)
  globalThis.fetch = original

  let put = 0
  globalThis.fetch = async (url, init) => {
    if (String(url).includes('/digest')) return Response.json({ digest: HEX, bytes: 3 })
    if (String(url).includes('/profiles/') && (!init || !init.method || init.method === 'GET')) {
      return Response.json({ digest: HEX, revision: 2, settings: { face } })
    }
    put++
    return new Response('{"detail":"conflict"}', { status: 409 })
  }
  try {
    const loaded = await loadFaceProfile('/api/v1/file/mira.glb?workspace=one', 'one')
    assert.equal(loaded.digest, HEX)
    assert.equal(loaded.revision, 2)
    await assert.rejects(() => saveFaceProfile(HEX, 'one', 1, speech()), /elsewhere/)
    assert.equal(put, 1)
  } finally { globalThis.fetch = original }
})
