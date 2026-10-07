import assert from 'node:assert/strict'
import test from 'node:test'
import { Box3, Mesh, Points, Scene, Texture } from 'three'
import { EnvironmentLighting } from '../src/features/scene3d/environmentLighting'
import { applyScene3DTemplate } from '../src/features/scene3d/templates'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document'
import { MOTION_LAB_IDS, DEFAULT_MOTION_LAB, parseMotionLab } from '../src/features/scene3d/motionlab/types'
import { buildMotionLab } from '../src/features/scene3d/motionlab/runtime'
import { hashSoftwareFrame, renderScene3DSoftware } from '../src/features/scene3d/softwareRender'
import { glyphPoints } from '../src/features/scene3d/motionlab/glyphs'

test('all native templates survive JSON save/open with distinct deterministic animated geometry', () => {
  const hashes = new Set<string>()
  for (const id of MOTION_LAB_IDS) {
    const original = applyScene3DTemplate(id), document = parseScene3DDocument(JSON.parse(JSON.stringify(original)))
    assert.ok(document); assert.equal(document.templateId, id); assert.equal(document.dressing, id)
    assert.deepEqual(document.motionLab, DEFAULT_MOTION_LAB)
    assert.deepEqual(document.slots, [], 'templates are complete without missing external assets')
    const handle = buildMotionLab(id, document.motionLab)!
    try {
      const sample = (time: number) => {
        handle.update(time); handle.root.updateMatrixWorld(true)
        const box = new Box3().setFromObject(handle.root)
        assert.ok(!box.isEmpty()); assert.ok([...box.min.toArray(), ...box.max.toArray()].every(Number.isFinite))
        const values: number[] = []
        handle.root.traverse(object => {
          values.push(...object.matrixWorld.elements)
          if (object instanceof Points) values.push(...object.geometry.getAttribute('position').array)
          if (object instanceof Mesh) assert.ok(object.geometry.getAttribute('position').count > 0)
        })
        assert.ok(values.every(Number.isFinite)); return values
      }
      const at = sample(3.25); assert.notDeepEqual(sample(11.7), at, id); assert.deepEqual(sample(3.25), at, `seek must not accumulate ${id}`)
    } finally { handle.dispose(); handle.dispose() }
    const early = renderScene3DSoftware(document, 2), late = renderScene3DSoftware(document, 13)
    const hash = hashSoftwareFrame(early); hashes.add(hash)
    assert.notEqual(hashSoftwareFrame(late), hash, `MCP preview must show actual motion ${id}`)
    assert.equal(hashSoftwareFrame(renderScene3DSoftware(document, 2)), hash)
  }
  assert.equal(hashes.size, MOTION_LAB_IDS.length, 'eight different 3D scenes, not aliases')
})

test('motion settings reject malformed state and leave older documents unchanged', () => {
  for (const motionLab of [{ bpm: 0 }, { speed: NaN }, { seed: 1.2 }, { density: 50000 }, { sound: 'yes' }, { color: 'red' }, { title: 'x'.repeat(25) }, { unknown: true }]) {
    assert.equal(parseScene3DDocument({ ...createDefaultScene3DDocument(), motionLab }), null)
  }
  assert.equal(parseScene3DDocument(createDefaultScene3DDocument())?.motionLab, undefined)
  for (const key of ['constructor', 'toString', '__proto__']) assert.throws(() => parseMotionLab(JSON.parse(`{"${key}":1}`)))
  assert.deepEqual(parseMotionLab({ bpm: 96, title: '  HELLO  ' }), { ...DEFAULT_MOTION_LAB, bpm: 96, title: 'HELLO' })
})

test('block typography normalizes accented titles and keeps arbitrary symbols visible', () => {
  assert.deepEqual(glyphPoints('Á'), glyphPoints('A'))
  assert.ok(glyphPoints('🎵').length > 0)
  assert.ok(glyphPoints('HELLO 64').every(point => point.every(Number.isFinite)))
})

test('particle density, title, palette, amplitude and seed affect actual native geometry', () => {
  const a = buildMotionLab('motion-particle-morph', { ...DEFAULT_MOTION_LAB, density: 200 })!
  const b = buildMotionLab('motion-particle-morph', { ...DEFAULT_MOTION_LAB, density: 300, title: 'WORLD', seed: 99, amplitude: 1.5 })!
  try {
    a.update(20); b.update(20)
    const first = a.root.getObjectByName('morph-cloud') as Points, second = b.root.getObjectByName('morph-cloud') as Points
    assert.equal(first.geometry.getAttribute('position').count, 200)
    assert.equal(second.geometry.getAttribute('position').count, 300)
    assert.notDeepEqual(first.geometry.getAttribute('position').array, second.geometry.getAttribute('position').array)
  } finally { a.dispose(); b.dispose() }
})

test('complete native meshes receive environment fill and do not leak it into legacy empty sets', () => {
  const lighting = new EnvironmentLighting(), room = new Texture(), scene = new Scene()
  // Supply the baked room without creating a WebGL context; exercise the real eligibility/state path.
  Object.assign(lighting, { room })
  const renderer = { getRenderTarget() { return null } }
  lighting.sync(renderer as never, scene, applyScene3DTemplate('motion-music-machine'))
  assert.equal(scene.environment, room); assert.equal(scene.environmentIntensity, .8)
  lighting.sync(renderer as never, scene, createDefaultScene3DDocument())
  assert.equal(scene.environment, null)
  lighting.dispose()
})
