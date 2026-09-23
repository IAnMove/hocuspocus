import test from 'node:test'
import assert from 'node:assert/strict'
import { Group, Mesh, MeshBasicMaterial, Object3D } from 'three'
import { bindScreenMedia } from '../src/features/scene3d/screenMediaRuntime.ts'
import { defaultMediaScreen } from '../src/features/scene3d/mediaScreen.ts'
import { SCREEN_PLANE_NAME } from '../src/features/scene3d/screenPlane.ts'
import { bindPortalMedia } from '../src/features/sceneFx/portalMediaRuntime.ts'
import { buildPackedEffect } from '../src/features/sceneFx/worldPack.ts'
import { prepareWorldSfxMedia, worldSfxMediaReady, worldSfxMediaTime } from '../src/features/sceneFx/worldRuntime.ts'

// Browser currentTime changes before decoding finishes. Keep seeked under the
// test's control to exercise overlapping preview/export requests independently.
function mediaHarness() {
  const previous = globalThis.document
  const video = new EventTarget()
  Object.assign(video, { currentTime: 0, duration: 6, videoWidth: 320, videoHeight: 180,
    pause() {}, removeAttribute() {}, load() { queueMicrotask(() => video.dispatchEvent(new Event('loadeddata'))) } })
  const frames = []
  const paint = { clears: 0, fills: 0 }
  const context = { clearRect() { paint.clears++ }, fillRect() { paint.fills++ }, drawImage(source) { frames.push(source.currentTime) } }
  globalThis.document = { createElement: kind => kind === 'video' ? video : { getContext: () => context } }
  const root = new Group(), original = new MeshBasicMaterial(), mesh = new Mesh(undefined, original)
  mesh.name = 'SCREEN_CONTENT'; root.add(mesh)
  return { video, frames, root, mesh, original, paint, finishSeek() { video.dispatchEvent(new Event('seeked')) },
    restore() { globalThis.document = previous; original.dispose() } }
}

test('transparent videos retain alpha instead of painting an opaque matte underneath', async () => {
  const h = mediaHarness(), screen = { ...defaultMediaScreen(), media: 'video', sourceUrl: '/actor.webm', transparent: true }
  const runtime = await bindScreenMedia(h.root, screen, true, new AbortController().signal)
  try {
    assert.equal(h.mesh.material.transparent, true)
    assert.equal(h.mesh.material.alphaTest, .05)
    assert.equal(h.paint.clears, 1); assert.equal(h.paint.fills, 0)
  } finally { runtime.dispose(); h.restore() }
})

test('color cleanup survives the moving-layer material clone and keeps letterboxing transparent', async () => {
  const h = mediaHarness(), screen = { ...defaultMediaScreen(), media: 'video', sourceUrl: '/lantern.mp4' }
  h.mesh.material.map = null
  const look = { colorKey: { color: '#c2cec5', tolerance: .06, softness: .04 }, psx: 1 }
  const runtime = await bindScreenMedia(h.mesh, screen, false, new AbortController().signal, () => {}, { look })
  try {
    const shader = { uniforms: {}, fragmentShader: '#include <map_fragment>\n#include <alphatest_fragment>' }
    h.mesh.material.onBeforeCompile(shader)
    assert.ok(shader.uniforms.hpKeyColor)
    assert.ok(shader.uniforms.hpPsxGrid)
    assert.equal(h.mesh.material.transparent, true)
    assert.equal(h.paint.clears, 1)
    assert.equal(h.paint.fills, 0, 'cleanup must not add a dark opaque frame around the source')
  } finally { runtime.dispose(); h.restore() }
})

test('no-op and same-target requests await decoded content and repaint on backward seek', async () => {
  const h = mediaHarness(), screen = { ...defaultMediaScreen(), media: 'video', sourceUrl: '/test.mp4' }
  const repaints = []
  const runtime = await bindScreenMedia(h.root, screen, true, new AbortController().signal, () => repaints.push(h.frames.at(-1)))
  try {
    const zero = runtime.seek(0, screen)
    const forward = runtime.seek(4, screen)
    assert.equal(h.video.currentTime, 4)
    let ready = false
    const same = runtime.seek(4, screen).then(() => { ready = true })
    await Promise.resolve()
    assert.equal(ready, false, 'the currentTime assignment does not prove frame readiness')
    h.finishSeek()
    await Promise.all([zero, forward, same])
    assert.equal(ready, true)
    assert.equal(repaints.at(-1), 4)
    const back = runtime.seek(1, screen)
    assert.equal(h.video.currentTime, 1)
    assert.equal(repaints.at(-1), 4)
    h.finishSeek(); await back
    assert.equal(repaints.at(-1), 1)
    const count = repaints.length
    runtime.dispose()
    assert.equal(h.mesh.material, h.original)
    h.finishSeek()
    assert.equal(repaints.length, count)
  } finally { runtime.dispose(); h.restore() }
})

test('a seek can settle from timeupdate when the decoder is already near the target', async () => {
  const h = mediaHarness(), screen = { ...defaultMediaScreen(), media: 'video', sourceUrl: '/test.mp4' }
  const runtime = await bindScreenMedia(h.root, screen, true, new AbortController().signal)
  try {
    const started = Date.now()
    const pending = runtime.seek(1, screen)
    await Promise.resolve()
    h.video.dispatchEvent(new Event('timeupdate'))
    await pending
    assert.ok(Date.now() - started < 500)
    assert.equal(h.video.currentTime, 1)
  } finally { runtime.dispose(); h.restore() }
})

test('a seek without seeked still settles so export cannot stall on every frame', async () => {
  const h = mediaHarness(), screen = { ...defaultMediaScreen(), media: 'video', sourceUrl: '/test.mp4' }
  const runtime = await bindScreenMedia(h.root, screen, true, new AbortController().signal)
  try {
    const started = Date.now()
    await runtime.seek(1, screen)
    assert.ok(Date.now() - started < 4_000)
    assert.equal(h.video.currentTime, 1)
    assert.equal(h.frames.at(-1), 1)
  } finally { runtime.dispose(); h.restore() }
})

test('a snapped decoded frame settles once so export does not reseek the same clock time', async () => {
  const h = mediaHarness(), screen = { ...defaultMediaScreen(), media: 'video', sourceUrl: '/test.mp4' }
  let time = 0, assignments = 0
  Object.defineProperty(h.video, 'currentTime', {
    configurable: true,
    get() { return time },
    set(value) { assignments += 1; time = Math.round(Number(value) * 24) / 24 },
  })
  const runtime = await bindScreenMedia(h.root, screen, true, new AbortController().signal)
  try {
    const pending = runtime.seek(1 / 30, screen)
    assert.equal(assignments, 1)
    assert.ok(Math.abs(h.video.currentTime - 1 / 30) > .0005)
    h.finishSeek()
    await Promise.race([pending, new Promise((_, reject) => setTimeout(() => reject(new Error('seek-did-not-settle')), 50))])
    assert.equal(assignments, 1)
    await runtime.seek(1 / 30, screen)
    assert.equal(assignments, 1)
  } finally { runtime.dispose(); h.restore() }
})

test('disposing a pending video seek rejects it and restores the GLB material', async () => {
  const h = mediaHarness(), screen = { ...defaultMediaScreen(), media: 'video', sourceUrl: '/test.mp4' }
  const runtime = await bindScreenMedia(h.root, screen, false, new AbortController().signal)
  try {
    const pending = runtime.seek(3, screen)
    const rejected = assert.rejects(pending, /screen-media-disposed/)
    runtime.dispose()
    await rejected
    assert.equal(h.mesh.material, h.original)
    assert.deepEqual(h.frames, [0])
  } finally { runtime.dispose(); h.restore() }
})

for (const flipY of [false, true]) test(`a bone plane uses native plane UV orientation (flip=${flipY})`, async () => {
  const h = mediaHarness(), head = new Object3D(); head.name = 'headfront'; h.root.add(head)
  const screen = { ...defaultMediaScreen(), mode: 'plane', anchor: 'headfront', media: 'video', sourceUrl: '/test.mp4', flipY }
  const runtime = await bindScreenMedia(h.root, screen, false, new AbortController().signal)
  try {
    const plane = head.getObjectByName(SCREEN_PLANE_NAME)
    assert.equal(plane.material.map.flipY, !flipY, 'new geometry uses the same UV convention as a standalone screen')
    assert.equal(h.mesh.material, h.original, 'the original GLB material stays intact')
    let disposed = 0
    plane.geometry.addEventListener('dispose', () => { disposed++ })
    runtime.dispose(); runtime.dispose()
    assert.equal(disposed, 1)
    assert.equal(head.children.length, 0)
  } finally { runtime.dispose(); h.restore() }
})

test('portal video follows cue time, waits for decoding and releases its texture', async () => {
  const h = mediaHarness(), root = buildPackedEffect('media_portal', '#ffaa88')
  const runtime = bindPortalMedia(root, '/world.mp4')
  const cue = { id: 'portal', kind: 'media_portal', sourceUrl: '/world.mp4', start: 2, end: 7 }
  const nodes = new Map([[cue.id, { root, kind: cue.kind, sourceUrl: cue.sourceUrl, media: runtime }]])
  try {
    assert.equal(worldSfxMediaReady(nodes, [cue]), false)
    await runtime.seek(0)
    assert.equal(worldSfxMediaReady(nodes, [cue]), true)
    assert.equal(worldSfxMediaReady(nodes, [{ ...cue, sourceUrl: '/new.mp4' }]), false)
    assert.equal(h.video.autoplay, undefined)
    const pending = prepareWorldSfxMedia(nodes, [cue], 5)
    await Promise.resolve(); await Promise.resolve()
    assert.equal(h.video.currentTime, 3)
    assert.equal(h.frames.at(-1), 0)
    h.finishSeek(); await pending
    assert.equal(h.frames.at(-1), 3)
    const back = prepareWorldSfxMedia(nodes, [cue], 2.5)
    await Promise.resolve(); await Promise.resolve()
    h.finishSeek(); await back
    assert.equal(h.frames.at(-1), .5)
    assert.equal(worldSfxMediaTime(cue, 0), 0)
    assert.equal(worldSfxMediaTime(cue, 9), 5)
    const uniforms = root.children.find(child => child.userData.kind === 'portalMedia').material.uniforms
    let released = 0
    uniforms.uMap.value.addEventListener('dispose', () => { released++ })
    runtime.dispose(); runtime.dispose()
    assert.equal(released, 1)
    assert.equal(uniforms.uHasMap.value, 0)
    assert.equal(uniforms.uMap.value, null)
  } finally { runtime.dispose(); h.restore() }
})

test('failed portal media blocks export, and disposal during loading cannot attach a stale texture', async () => {
  const h = mediaHarness(), root = buildPackedEffect('media_portal', '#ffaa88')
  h.video.load = () => {}
  const runtime = bindPortalMedia(root, '/missing.mp4')
  try {
    const failure = assert.rejects(runtime.seek(0), /screen-media-load-failed/)
    h.video.dispatchEvent(new Event('error')); await failure
    const cue = { id: 'p', kind: 'media_portal', sourceUrl: '/missing.mp4' }
    assert.throws(() => worldSfxMediaReady(new Map([['p', { ...cue, media: runtime }]]), [cue]), /screen-media-load-failed/)
    runtime.dispose()
    const pending = bindPortalMedia(root, '/late.mp4')
    pending.dispose(); h.video.dispatchEvent(new Event('loadeddata'))
    await pending.seek(0)
    const uniforms = root.children.find(child => child.userData.kind === 'portalMedia').material.uniforms
    assert.equal(uniforms.uMap.value, null)
    assert.equal(pending.ready, false)
  } finally { runtime.dispose(); h.restore() }
})

test('portals sharing a URL keep independent playback and disposal', async () => {
  const first = mediaHarness(), a = bindPortalMedia(buildPackedEffect('media_portal', '#ffaa88'), '/same.mp4')
  const second = mediaHarness(), b = bindPortalMedia(buildPackedEffect('media_portal', '#ffaa88'), '/same.mp4')
  try {
    await Promise.all([a.seek(0), b.seek(0)])
    const seekA = a.seek(4), seekB = b.seek(1)
    await Promise.resolve()
    assert.equal(first.video.currentTime, 4)
    assert.equal(second.video.currentTime, 1)
    first.finishSeek(); second.finishSeek(); await Promise.all([seekA, seekB])
    a.dispose()
    const next = b.seek(2)
    await Promise.resolve(); second.finishSeek(); await next
    assert.equal(second.frames.at(-1), 2)
  } finally { a.dispose(); b.dispose(); second.restore(); first.restore() }
})

test('a wall of CRTs playing one clip shares a decoder and seeks it once per frame', async () => {
  const h = mediaHarness(), create = globalThis.document.createElement
  let videos = 0, assignments = 0, time = 0
  globalThis.document.createElement = kind => {
    if (kind === 'video') { videos++; return create(kind) }
    const element = create(kind), context = element.getContext()
    context.createRadialGradient = context.createLinearGradient = () => ({ addColorStop() {} })
    return element
  }
  // The CRT overlay is drawn too; count only video frames.
  const shown = () => h.frames.filter(frame => frame !== undefined)
  Object.defineProperty(h.video, 'currentTime', { configurable: true, get() { return time }, set(value) { assignments++; time = value } })
  const screen = { ...defaultMediaScreen(), media: 'video', style: 'crt', sourceUrl: '/wall.mp4' }
  const roots = [0, 1, 2].map(() => { const root = new Group(), mesh = new Mesh(undefined, new MeshBasicMaterial()); mesh.name = 'SCREEN_CONTENT'; root.add(mesh); return root })
  const tvs = await Promise.all(roots.map(root => bindScreenMedia(root, screen, true, new AbortController().signal)))
  try {
    assert.equal(videos, 1)
    const frames = shown().length
    const seeks = tvs.map(tv => tv.seek(2, screen))
    h.finishSeek(); await Promise.all(seeks)
    assert.equal(assignments, 1)
    assert.equal(shown().length - frames, 3, 'every TV repaints the shared frame')
    tvs[0].dispose()
    const next = tvs[1].seek(3, screen); h.finishSeek(); await next
    assert.equal(shown().at(-1), 3, 'the others keep playing after one TV is removed')
  } finally { tvs.forEach(tv => tv.dispose()); h.restore() }
})
