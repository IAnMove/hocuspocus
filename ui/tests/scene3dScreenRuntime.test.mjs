import test from 'node:test'
import assert from 'node:assert/strict'
import { Group, Mesh, MeshBasicMaterial, Object3D } from 'three'
import { bindScreenMedia } from '../src/features/scene3d/screenMediaRuntime.ts'
import { defaultMediaScreen } from '../src/features/scene3d/mediaScreen.ts'
import { SCREEN_PLANE_NAME } from '../src/features/scene3d/screenPlane.ts'

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
