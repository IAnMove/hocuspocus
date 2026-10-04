import assert from 'node:assert/strict'
import test from 'node:test'
import { BoxGeometry, Color, FogExp2, Mesh, MeshStandardMaterial, NearestFilter, Scene, Texture } from 'three'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyN64Look, withN64Look } from '../src/features/scene3d/n64Look.ts'

test('N64 preset reuses whole-frame pixel pass without mutating the authored document', () => {
  const original = { ...createDefaultScene3DDocument(), renderLook: 'n64', environment: { bloom: 2 } }
  const effective = withN64Look(original)
  assert.equal(effective.pixelWorld.pixelSize, 3)
  assert.equal(effective.pixelWorld.levels, 32)
  assert.equal(effective.pixelWorld.dither, 0)
  assert.equal(effective.environment.bloom, 0)
  assert.equal(original.environment.bloom, 2)
  assert.equal(original.pixelWorld, undefined)
  const normal = createDefaultScene3DDocument()
  assert.equal(withN64Look(normal), normal)
})

test('all model materials use flat shading, nearest textures and close fog then restore', () => {
  const scene = new Scene()
  scene.background = new Color('#8abcd0')
  const originalFog = new FogExp2('#eeeeee', .02)
  scene.fog = originalFog
  const map = new Texture()
  const originalMin = map.minFilter, originalMag = map.magFilter
  const material = new MeshStandardMaterial({ map, flatShading: false })
  const mesh = new Mesh(new BoxGeometry(), [material, new MeshStandardMaterial()])
  scene.add(mesh)
  applyN64Look(scene, true)
  const retroFog = scene.fog
  assert.equal(retroFog.near, 4)
  assert.equal(retroFog.far, 28)
  assert.ok(retroFog.color.equals(scene.background))
  assert.ok(mesh.material.every(m => m.flatShading))
  assert.equal(map.minFilter, NearestFilter)
  assert.equal(map.magFilter, NearestFilter)
  const version = material.version
  applyN64Look(scene, true)
  assert.equal(material.version, version)
  assert.equal(scene.fog, retroFog)
  const newMaterial = new MeshStandardMaterial()
  scene.add(new Mesh(new BoxGeometry(), newMaterial))
  applyN64Look(scene, true)
  assert.equal(newMaterial.flatShading, true)
  applyN64Look(scene, false)
  assert.equal(material.flatShading, false)
  assert.equal(newMaterial.flatShading, false)
  assert.equal(map.minFilter, originalMin)
  assert.equal(map.magFilter, originalMag)
  assert.equal(scene.fog, originalFog)
  // An authored atmosphere that changes during sync must survive disabling.
  applyN64Look(scene, true)
  const nextFog = new FogExp2('#778899', .1)
  scene.fog = nextFog
  applyN64Look(scene, true)
  applyN64Look(scene, false)
  assert.equal(scene.fog, nextFog)
  material.dispose(); mesh.geometry.dispose(); newMaterial.dispose(); map.dispose()
})


test('render look survives document persistence and rejects unknown presets', () => {
  const doc = { ...createDefaultScene3DDocument(), renderLook: 'n64' }
  assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(doc))).renderLook, 'n64')
  assert.equal(parseScene3DDocument({ ...doc, renderLook: 'unknown' }), null)
})
