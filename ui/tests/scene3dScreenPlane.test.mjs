import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Object3D, Vector3 } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { defaultMediaScreen, defaultModelScreen, parseMediaScreen, pickScreenAnchor } from '../src/features/scene3d/mediaScreen.ts'
import { SCREEN_PLANE_NAME, attachScreenPlane, detachScreenPlane, isGeneratedScreenPlane, namedSceneMeshes, namedSceneNodes } from '../src/features/scene3d/screenPlane.ts'
import { faceMeshes, manualFace } from '../src/features/scene3d/speech/calibration.ts'

test('Meshy-style TV heads default to a plane on headfront, not the body mesh', () => {
  const names = ['Mesh_0', 'Armature', 'Hips', 'Head', 'headfront', 'head_end']
  assert.equal(pickScreenAnchor(names), 'headfront')
  const screen = defaultModelScreen(names)
  assert.equal(screen.mode, 'plane')
  assert.equal(screen.anchor, 'headfront')
  assert.ok(screen.width < 1)
  assert.ok(screen.height < 1)
})

test('a screen plane is parented to headfront and follows the bone', () => {
  const root = new Group()
  const head = new Object3D(); head.name = 'Head'; root.add(head)
  const headfront = new Object3D(); headfront.name = 'headfront'; head.add(headfront)
  const screen = { ...defaultModelScreen(['headfront']), width: 0.3, height: 0.2 }
  const plane = attachScreenPlane(root, screen)
  assert.equal(plane.name, SCREEN_PLANE_NAME)
  assert.equal(plane.parent, headfront)
  headfront.position.set(0.4, 1.2, 0.1)
  headfront.updateMatrixWorld(true)
  const world = new Vector3()
  plane.getWorldPosition(world)
  assert.ok(Math.abs(world.x - 0.4) < 1e-6)
  assert.ok(Math.abs(world.y - 1.2) < 1e-6)
  detachScreenPlane(root)
  assert.equal(headfront.children.length, 0)
})

test('plane attachment and offset survive JSON reopen', () => {
  const parsed = parseMediaScreen({
    ...defaultMediaScreen(), mode: 'plane', anchor: 'headfront', offset: [0, 0.02, 0.01],
    pitch: 1.2, yaw: 0.5, roll: -0.7, width: 0.28, height: 0.18, sourceUrl: '/api/v1/uploads/face.png',
  })
  assert.equal(parsed.mode, 'plane')
  assert.equal(parsed.anchor, 'headfront')
  assert.deepEqual(parsed.offset, [0, 0.02, 0.01])
  assert.equal(parsed.yaw, 0.5)
  assert.equal(parsed.pitch, 1.2)
  assert.equal(parsed.roll, -0.7)
  assert.equal(parsed.width, 0.28)
  assert.equal(parsed.sourceUrl, '/api/v1/uploads/face.png')
})

test('Meshy headfront frame produces a front-facing upright plane', () => {
  const root = new Group(), head = new Object3D(); head.name = 'headfront'; root.add(head)
  // Measured axes in the supplied GLB: bone X=-worldX, Y=worldZ, Z=worldY.
  head.rotation.set(Math.PI / 2, Math.PI, 0)
  const plane = attachScreenPlane(root, defaultModelScreen(['headfront']))
  root.updateMatrixWorld(true)
  assert.ok(new Vector3(0, 0, 1).transformDirection(plane.matrixWorld).distanceTo(new Vector3(0, 0, 1)) < 1e-6)
  assert.ok(new Vector3(0, 1, 0).transformDirection(plane.matrixWorld).distanceTo(new Vector3(0, 1, 0)) < 1e-6)
  detachScreenPlane(root)
})

test('painting picks real meshes and preserves prepared monitor surfaces', () => {
  const root = new Group(); root.name = 'Armature'
  const bone = new Object3D(); bone.name = 'Head'; root.add(bone)
  const body = new Mesh(); body.name = 'Mesh_0'; root.add(body)
  assert.deepEqual(namedSceneMeshes(root), ['Mesh_0'])
  assert.equal(defaultModelScreen(namedSceneNodes(root), namedSceneMeshes(root)).targetMesh, 'Mesh_0')
  const display = new Mesh(); display.name = 'SCREEN_CONTENT'; root.add(display)
  const screen = defaultModelScreen(namedSceneNodes(root), namedSceneMeshes(root))
  assert.equal(screen.mode, 'mesh')
  assert.equal(screen.targetMesh, 'SCREEN_CONTENT')
})

test('cleanup never destroys an original GLB mesh with the generated plane name', () => {
  const root = new Group(), head = new Object3D(), original = new Mesh()
  head.name = 'headfront'; original.name = SCREEN_PLANE_NAME; root.add(head, original)
  let disposed = 0
  original.geometry.addEventListener('dispose', () => { disposed++ })
  const plane = attachScreenPlane(root, defaultModelScreen(['headfront']))
  detachScreenPlane(root, plane)
  assert.equal(original.parent, root)
  assert.equal(disposed, 0)
})

test('a stale cleanup cannot remove the replacement plane', () => {
  const root = new Group(), head = new Object3D(); head.name = 'headfront'; root.add(head)
  const screen = defaultModelScreen(['headfront'])
  const old = attachScreenPlane(root, screen), current = attachScreenPlane(root, screen)
  detachScreenPlane(root, old)
  assert.equal(current.parent, head)
  assert.equal(head.children.length, 1)
  detachScreenPlane(root, current)
  assert.equal(head.children.length, 0)
})

test('a headfront plane does not shift speech face mesh indices on Meshy-style armatures', () => {
  const root = new Group()
  const hips = new Object3D(); hips.name = 'Hips'; root.add(hips)
  const head = new Object3D(); head.name = 'Head'; hips.add(head)
  const headfront = new Object3D(); headfront.name = 'headfront'; head.add(headfront)
  const body = new Mesh(new BoxGeometry(1, 2, .5), new MeshStandardMaterial()); body.name = 'Mesh_0'; root.add(body)
  const face = manualFace(root)
  assert.equal(face.meshIndex, 0)
  assert.equal(faceMeshes(root)[0], body)
  const plane = attachScreenPlane(root, defaultModelScreen(['headfront']))
  assert.equal(plane.parent, headfront)
  assert.ok(isGeneratedScreenPlane(plane))
  assert.equal(faceMeshes(root).length, 1)
  assert.equal(faceMeshes(root)[face.meshIndex], body)
})

test('an original GLB mesh named like the generated plane stays in the speech catalog', () => {
  const root = new Group()
  const original = new Mesh(new BoxGeometry(1, 2, .5), new MeshStandardMaterial())
  original.name = SCREEN_PLANE_NAME
  root.add(original)
  assert.equal(faceMeshes(root)[0], original)
  assert.equal(isGeneratedScreenPlane(original), false)
})

test('TV-head example fixture loads as a GLB with headfront and Walking', async () => {
  const glb = readFileSync(join(dirname(fileURLToPath(import.meta.url)), './fixtures/tv-head-humanoid.glb'))
  assert.ok(glb.length > 1000)
  assert.ok(glb.length < 20000)
  const jsonLength = glb.readUInt32LE(12)
  const json = JSON.parse(glb.subarray(20, 20 + jsonLength).toString('utf8'))
  assert.equal(json.asset.version, '2.0')
  const loaded = await new GLTFLoader().parseAsync(glb.buffer.slice(glb.byteOffset, glb.byteOffset + glb.byteLength), '')
  assert.ok(loaded.scene.getObjectByName('headfront'))
  assert.ok(loaded.scene.getObjectByName('LeftUpLeg'))
  assert.ok(loaded.animations.some(clip => clip.name === 'Walking'))
})
