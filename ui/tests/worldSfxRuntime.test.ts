import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Object3D, Scene, Vector3 } from 'three'
import { applyWorldSfxTranslate, parseWorldSfx, worldAnchorOffsetFromWorldPoint } from '../src/features/sceneFx/world'
import { syncWorldSfx, worldAnchorOffsetFromSlotRoot } from '../src/features/sceneFx/worldRuntime'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { worldSfxDuelDocument } from '../src/features/sceneFx/worldDemo'
import { transformPatch } from '../src/features/scene3d/transformGizmo.ts'

test('world SFX occupy the scene graph and hide outside their window', () => {
  const scene = new Scene()
  const nodes = new Map()
  const cues = parseWorldSfx([
    { id: 'gate', kind: 'portal', start: 1, end: 4, position: { x: 0, y: 1, z: -2 } },
    { id: 'ring', kind: 'magic_circle', start: 0, end: 8, position: { x: 0, y: 0.02, z: 0 } },
  ])
  syncWorldSfx(scene, nodes, cues, 0, [])
  assert.equal(nodes.get('gate')?.root.visible, false)
  assert.equal(nodes.get('ring')?.root.visible, true)
  assert.equal(nodes.get('gate')?.root.position.z, -2)
  syncWorldSfx(scene, nodes, cues, 2, [{ id: 'subject_1', position: [1, 0, 0], rotationY: 0 }])
  assert.equal(nodes.get('gate')?.root.visible, true)
  const same = nodes.get('gate')?.root
  syncWorldSfx(scene, nodes, cues, 2.5, [])
  assert.equal(nodes.get('gate')?.root, same)
  syncWorldSfx(scene, nodes, cues.filter(cue => cue.id === 'ring'), 3, [])
  assert.equal(nodes.has('gate'), false)
  assert.equal(nodes.has('ring'), true)
})

test('a beam follows two moving slot roots and a missing anchor stays put', () => {
  const scene = new Scene()
  const nodes = new Map()
  const a = new Object3D(); a.position.set(-2, 1, 0)
  const b = new Object3D(); b.position.set(2, 1, 0)
  const cues = parseWorldSfx([{
    id: 'beam', kind: 'energy_beam', start: 0, end: 4,
    anchor: { slotId: 'subject_1' }, target: { slotId: 'subject_2' },
  }])
  syncWorldSfx(scene, nodes, cues, 1, [
    { id: 'subject_1', position: [-2, 0, 0], rotationY: 0, root: a },
    { id: 'subject_2', position: [2, 0, 0], rotationY: 0, root: b },
  ])
  const shaft = nodes.get('beam')?.root.children.find(child => child.userData.kind === 'beam')
  assert.ok(shaft)
  assert.ok(Math.abs(shaft.position.x) < 0.05)
  a.position.x = -3
  b.position.x = 3
  a.updateMatrixWorld(true); b.updateMatrixWorld(true)
  syncWorldSfx(scene, nodes, cues, 1.2, [
    { id: 'subject_1', position: [-3, 0, 0], rotationY: 0, root: a },
    { id: 'subject_2', position: [3, 0, 0], rotationY: 0, root: b },
  ])
  assert.ok(Math.abs(shaft.position.x) < 0.05)
  syncWorldSfx(scene, nodes, cues, 1.4, [])
  const marker = nodes.get('beam')?.root.children.find(child => child.userData.kind === 'missing')
  assert.equal(marker?.visible, true)
})

test('all 64 world cues stay in the scene graph and hidden ones stay unselectable', () => {
  const scene = new Scene()
  const nodes = new Map()
  const cues = parseWorldSfx(Array.from({ length: 40 }, (_, i) => ({
    id: `fx-${i}`, kind: i % 2 ? 'portal' : 'magic_circle', start: i < 5 ? 0 : 8, end: i < 5 ? 4 : 12,
    position: { x: i, y: 1, z: 0 },
  })))
  syncWorldSfx(scene, nodes, cues, 1, [])
  assert.equal(nodes.size, 40)
  assert.equal([...nodes.values()].filter(item => item.root.visible).length, 5)
  const late = nodes.get('fx-30')
  assert.equal(late?.root.visible, false)
  assert.ok(late?.root.userData.gizmoAt)
})

test('gizmo offset for an anchored cue is the slot-local displacement', () => {
  const slot = { position: [1, 0, 2] as const, rotationY: Math.PI / 2 }
  const offset = worldAnchorOffsetFromWorldPoint(slot, [1, 0.4, 3])
  assert.ok(Math.abs(offset.x + 1) < 1e-6)
  assert.equal(Number(offset.y.toFixed(4)), 0.4)
  assert.ok(Math.abs(offset.z) < 1e-6)
})

test('anchored gizmo writes use the live pose, not the rest slot', () => {
  const duel = worldSfxDuelDocument()
  const slot = duel.slots.find(item => item.id === 'subject_1')
  const cue = duel.worldSfx?.find(item => item.id === 'duel-circle')
  assert.ok(slot && cue)
  const mid = slotPoseAtTime(slot, 5, duel.duration)
  const worldPoint: [number, number, number] = [mid.position[0] + 0.15, mid.position[1] + 0.02, mid.position[2]]
  const restOffset = worldAnchorOffsetFromWorldPoint(slot, worldPoint)
  const live = applyWorldSfxTranslate(cue, worldPoint, mid)
  assert.ok(Math.abs(restOffset.x - (live.anchor?.offset?.x ?? 0)) > 0.4, 'rest-pose inverse teleports the cue on a moving slot')
  assert.ok(Math.abs(live.anchor?.offset?.x ?? 99) < 0.2)
  assert.equal(Number((live.anchor?.offset?.y ?? 0).toFixed(2)), 0.02)
})

test('GPU local offset inverts a scaled moving slot root', () => {
  const root = new Object3D()
  root.position.set(-0.4, 0, 0.3)
  root.rotation.y = 0.4
  root.scale.setScalar(0.35)
  root.updateMatrixWorld(true)
  const world: [number, number, number] = [-0.1, 0.9, 0.55]
  const local = worldAnchorOffsetFromSlotRoot(root, world)
  const cue = parseWorldSfx([{
    id: 'orb', kind: 'energy_orb', start: 0, end: 4,
    anchor: { slotId: 'subject_1' },
  }])[0]
  const next = applyWorldSfxTranslate(cue, world, undefined, local)
  const back = root.localToWorld(new Vector3(next.anchor?.offset?.x ?? 0, next.anchor?.offset?.y ?? 0, next.anchor?.offset?.z ?? 0))
  assert.ok(Math.abs(back.x - world[0]) < 1e-6)
  assert.ok(Math.abs(back.y - world[1]) < 1e-6)
  assert.ok(Math.abs(back.z - world[2]) < 1e-6)
})

test('world gizmo exposes XYZ rotation instead of yaw-only', () => {
  const proxy = new Object3D()
  proxy.rotation.set(0.2, 0.4, -0.1)
  proxy.position.set(1, 2, 3)
  proxy.scale.setScalar(1.4)
  assert.deepEqual(transformPatch(proxy, 'translate', 'X', true).position, [1, 2, 3])
  const rotation = transformPatch(proxy, 'rotate', 'X', true).worldRotation
  assert.ok(rotation)
  assert.equal(Number(rotation[0].toFixed(4)), 0.2)
  assert.equal(transformPatch(proxy, 'rotate', 'Y', false).rotationY, 0.4)
})

test('animated portals preserve full rotations, zero-size birth and reversible seeking', async () => {
  const { worldSfxAtTime, setWorldMotionPose, parseWorldMotion } = await import('../src/features/sceneFx/worldMotion')
  const pose = (time: number, scale: number, z: number) => ({ time, scale, position: { x: time, y: 2, z: -1 }, rotation: { x: 0, y: 0, z }, easing: 'linear' })
  const cue = parseWorldSfx([{ id: 'jump', kind: 'media_portal', start: 0, end: 4,
    motion: [pose(2, 20, 720), pose(0, 0, 0), pose(2, 24, 720), { time: NaN }],
    mediaProjection: 'screen', mediaPlayback: { start: 2.4, speed: .6, loop: false },
  }])[0]
  assert.equal(cue.motion?.length, 2)
  assert.equal(worldSfxAtTime(cue, -1).scale, 0)
  assert.equal(worldSfxAtTime(cue, 1).rotation.z, 360)
  assert.equal(worldSfxAtTime(cue, 1).scale, 12)
  assert.equal(worldSfxAtTime(cue, 5).scale, 24)
  assert.deepEqual(parseWorldSfx(JSON.parse(JSON.stringify([cue])))[0], cue)
  const nodes = new Map(), scene = new Scene()
  syncWorldSfx(scene, nodes, [cue], 1, [], { width: 720, height: 1280 })
  const root = nodes.get(cue.id).root
  assert.equal(root.scale.x, 12)
  assert.equal(root.rotation.z, Math.PI * 2)
  const glass = root.children.find(child => child.userData.kind === 'portalMedia')
  assert.deepEqual(glass.material.uniforms.uViewport.value.toArray(), [720, 1280])
  assert.equal(glass.material.uniforms.uScreenSpace.value, 1)
  syncWorldSfx(scene, nodes, [cue], 0, [])
  assert.equal(nodes.get(cue.id).root.scale.x, 0)
  const edited = setWorldMotionPose(cue, 1, { ...worldSfxAtTime(cue, 1), scale: 7 })
  assert.equal(edited.motion?.length, 3)
  assert.equal(worldSfxAtTime(edited, 1).scale, 7)
  assert.equal(worldSfxAtTime(edited, 2).scale, 24)
  assert.equal(parseWorldMotion([pose(700, 100, 720)])?.[0].time, 600)
  assert.equal(parseWorldMotion([pose(0, 100, 720)])?.[0].scale, 64)
  syncWorldSfx(scene, nodes, [], 0, [])
})
