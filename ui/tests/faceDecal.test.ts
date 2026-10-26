import assert from 'node:assert/strict'
import test from 'node:test'
import { Bone, Matrix4, Mesh, MeshBasicMaterial, Object3D, Vector3 } from 'three'
import { ToonLook } from '../src/features/scene3d/toonLook.ts'
import { talkStateAt } from '../src/features/scene3d/talkingCutout.ts'
import {
  bindInverse, boneMatches, cutoutOf, faceCapGeometry, findBone, isFaceDecal, markFaceDecal,
  parseFaceDecal, placeFaceCap, poseAt,
} from '../src/features/scene3d/faceDecal.ts'

const mouth = { offsetX: 0, offsetY: 17, scale: 0.2, rotation: 0 }
const eyes = { offsetX: 0, offsetY: 0, scale: 1, rotation: 0 }

test('the cap covers the front past ±35° and the whole texture', () => {
  const geometry = faceCapGeometry()
  const position = geometry.getAttribute('position')
  const uv = geometry.getAttribute('uv')
  let minAngle = Infinity, maxAngle = -Infinity, minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity
  for (let index = 0; index < position.count; index += 1) {
    const x = position.getX(index), z = position.getZ(index)
    if (z > 0.05) {
      const angle = Math.atan2(x, z)
      minAngle = Math.min(minAngle, angle)
      maxAngle = Math.max(maxAngle, angle)
    }
    minU = Math.min(minU, uv.getX(index)); maxU = Math.max(maxU, uv.getX(index))
    minV = Math.min(minV, uv.getY(index)); maxV = Math.max(maxV, uv.getY(index))
  }
  assert.ok(minAngle <= -35 * Math.PI / 180, `left ${minAngle}`)
  assert.ok(maxAngle >= 35 * Math.PI / 180, `right ${maxAngle}`)
  assert.ok(minU < 0.05 && maxU > 0.95 && minV < 0.05 && maxV > 0.95)
  // 80° up and down like the 80° across, not pole to pole: a square face image must not be stretched 2.25 times.
  let maxY = 0
  for (let index = 0; index < position.count; index += 1) maxY = Math.max(maxY, Math.abs(position.getY(index)))
  assert.ok(Math.abs(maxY - Math.sin(40 * Math.PI / 180)) < 0.02, `vertical reach ${maxY}`)
})

test('toon look leaves the face cap flat and without an ink hull', () => {
  const root = new Object3D()
  const mesh = new Mesh(faceCapGeometry(), new MeshBasicMaterial({ color: 0xfff6f0 }))
  markFaceDecal(mesh)
  root.add(mesh)
  const look = new ToonLook()
  look.sync({ steps: 3, outline: 4, ink: '#141018' }, [{ root, outline: true }])
  let kind = ''
  let ink = 0
  look.draw(() => {
    kind = (mesh.material as MeshBasicMaterial).type
    mesh.traverse(object => { if (object.name.includes('toon-ink')) ink += 1 })
  })
  assert.equal(kind, 'MeshBasicMaterial')
  assert.equal(ink, 0)
  assert.equal(isFaceDecal(mesh), true)
  look.dispose()
})

test('a head bone turned 90° still puts the cap center on the model and +Z forward', () => {
  const root = new Object3D()
  const bone = new Bone()
  bone.name = 'mixamorigHead'
  bone.rotation.y = Math.PI / 2
  root.add(bone)
  root.updateMatrixWorld(true)
  assert.equal(findBone(root, 'Head'), bone)
  assert.equal(boneMatches('overhead', 'Head'), false)
  const mesh = new Mesh(faceCapGeometry())
  placeFaceCap(mesh, bindInverse(root, bone), [0, 1.5, 0], [0.31, 0.29, 0.275], 1.04)
  bone.add(mesh)
  root.updateMatrixWorld(true)
  const center = new Vector3().setFromMatrixPosition(mesh.matrixWorld)
  assert.ok(center.distanceTo(new Vector3(0, 1.5, 0)) < 1e-5, center.toArray().join())
  const front = new Vector3(0, 0, 1).applyMatrix4(mesh.matrixWorld).sub(center).normalize()
  assert.ok(front.z > 0.99 && Math.abs(front.x) < 1e-4 && Math.abs(front.y) < 1e-4, front.toArray().join())

  const plain = new Object3D()
  placeFaceCap(plain, new Matrix4(), [1, 2, 3], [0.4, 0.5, 0.6], 1)
  assert.deepEqual(plain.position.toArray(), [1, 2, 3])
  assert.deepEqual(plain.scale.toArray().map(value => Math.round(value * 1000) / 1000), [0.4, 0.5, 0.6])
  assert.ok(plain.quaternion.angleTo(plain.quaternion.clone().identity()) < 1e-6)
})

test('an expression at its start wins, and the stored art is a talking cutout', () => {
  assert.equal(poseAt({ pose: 'neutral', expressions: [{ start: 2, pose: 'happy' }] }, 1.9), 'neutral')
  assert.equal(poseAt({ pose: 'neutral', expressions: [{ start: 2, pose: 'happy' }] }, 2), 'happy')
  const art = {
    poses: { neutral: { base: '/api/v1/file/n.png?workspace=s', mouth, eyes, blink: '/api/v1/file/b.png?workspace=s' } },
    mouths: { closed: '/api/v1/file/c.png?workspace=s', wide: '/api/v1/file/w.png?workspace=s' },
    rest: 'closed', cues: [{ start: 0.1, end: 0.4, state: 'wide' }], blinks: [0.5],
  }
  const cutout = cutoutOf(art, 'neutral')
  assert.ok(cutout)
  assert.equal(cutout?.blink?.source, '/api/v1/file/b.png?workspace=s')
  assert.equal(cutout?.blink?.anchor.scale, 1)
  assert.equal(talkStateAt(cutout!, 0.2), 'wide')
  assert.equal(parseFaceDecal({ kitId: '' }), undefined)
  const kept = parseFaceDecal({ kitId: 'blob', radii: [-1, 0.2, 0.2], art })
  assert.equal(kept?.radii, undefined)
  assert.equal(kept?.art?.rest, 'closed')
  assert.doesNotThrow(() => parseFaceDecal({ kitId: 'blob', center: 'nope', art: { poses: null } }))
})
