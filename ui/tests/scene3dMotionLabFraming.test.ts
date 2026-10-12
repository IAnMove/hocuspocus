import assert from 'node:assert/strict'
import test from 'node:test'
import { Color, Mesh, PerspectiveCamera, Points, Vector3 } from 'three'
import { applyScene3DTemplate } from '../src/features/scene3d/templates'
import { buildMotionLab, motionLabSky } from '../src/features/scene3d/motionlab/runtime'
import { ScenicBuilder } from '../src/features/scene3d/motionlab/scenicShared'
import { DEFAULT_MOTION_LAB } from '../src/features/scene3d/motionlab/types'
import { hashSoftwareFrame, renderScene3DSoftware } from '../src/features/scene3d/softwareRender'

test('short and long titles and maximum particle expansion stay inside their authored cameras', () => {
  for (const id of ['motion-poster-breakout', 'motion-particle-morph'] as const) {
    const document = applyScene3DTemplate(id)
    const camera = new PerspectiveCamera(document.camera.fov, document.width / document.height, .1, 200)
    camera.position.set(...document.camera.eye); camera.lookAt(...document.camera.look); camera.updateMatrixWorld(true)
    for (const title of ['', 'A', 'W'.repeat(24), '😀'.repeat(12)]) {
      for (const amplitude of [1, 3]) for (const speed of [.1, 1, 3]) {
        const handle = buildMotionLab(id, { ...DEFAULT_MOTION_LAB, title, amplitude, speed, density: 3000, seed: 2147483647 })!
        try {
          const subject = handle.root.getObjectByName(id === 'motion-poster-breakout' ? 'volume-title' : 'morph-cloud')
          assert.ok(subject instanceof Mesh || subject instanceof Points)
          const attribute = subject.geometry.getAttribute('position'), vertex = new Vector3()
          for (const time of [0, 2, 5, 5.7, 7, 9, 12, 15, 18, 20, 23.7, 24]) {
            handle.update(time); handle.root.updateMatrixWorld(true)
            for (let index = 0; index < attribute.count; index++) {
              vertex.fromBufferAttribute(attribute, index).applyMatrix4(subject.matrixWorld).project(camera)
              assert.ok(vertex.toArray().every(Number.isFinite), `${id}: finite projection`)
              assert.ok(Math.abs(vertex.x) <= 1 && Math.abs(vertex.y) <= 1 && vertex.z >= -1 && vertex.z <= 1,
                `${id}: title=${JSON.stringify(title)} amplitude=${amplitude} speed=${speed} t=${time} leaves the frame`)
            }
          }
        } finally { handle.dispose() }
      }
    }
  }
})

test('CPU carriage preview sees the seasonal scenery through its transparent glass', () => {
  const document = applyScene3DTemplate('motion-seasonal-carriage')
  const seasons = [2, 10, 18, 26]
  const original = seasons.map(time => hashSoftwareFrame(renderScene3DSoftware(document, time)))
  assert.equal(new Set(original).size, 4, 'all four seasons remain visually distinct in the actual CPU preview')
  const box = ScenicBuilder.prototype.box
  let hiddenWindows = 0
  ScenicBuilder.prototype.box = function (this: ScenicBuilder, ...args: Parameters<typeof box>) {
    const mesh = box.apply(this, args)
    if (args[0] === 'window-glass') { mesh.visible = false; hiddenWindows++ }
    return mesh
  }
  try {
    assert.deepEqual(seasons.map(time => hashSoftwareFrame(renderScene3DSoftware(document, time))), original,
      'removing barely visible glass must not reveal a landscape that the CPU preview previously hid')
    assert.equal(hiddenWindows, seasons.length)
  } finally { ScenicBuilder.prototype.box = box }
})

test('CPU previews retain foreground water when the large sea crosses the camera near plane', () => {
  for (const id of ['motion-sunset-flight', 'motion-lighthouse-story'] as const) {
    const document = applyScene3DTemplate(id)
    const sky = new Color(motionLabSky(id)).convertLinearToSRGB().toArray().map(value => Math.floor(value * 255))
    for (const time of [0, 8, 28]) {
      const frame = renderScene3DSoftware(document, time)
      for (const fraction of [.03, .5, .97]) {
        const x = Math.floor(frame.width * fraction), y = frame.height - 5
        const offset = (y * frame.width + x) * 4
        assert.notDeepEqual([...frame.pixels.slice(offset, offset + 3)], sky,
          `${id}: t=${time} foreground water disappeared at x=${x}`)
      }
    }
  }
})
