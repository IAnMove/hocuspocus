import assert from 'node:assert/strict'
import test from 'node:test'
import { Box3, Mesh, MeshStandardMaterial, Vector3, type Object3D } from 'three'
import { buildDataAssembly, buildLighthouseStory, buildSeasonalCarriage, buildSunsetFlight } from '../src/features/scene3d/motionlab/scenic'
import { DEFAULT_MOTION_LAB, type MotionLabHandle, type MotionLabSettings } from '../src/features/scene3d/motionlab/types'

const builders = { buildSunsetFlight, buildSeasonalCarriage, buildDataAssembly, buildLighthouseStory }
const settings = (patch: Partial<MotionLabSettings> = {}): MotionLabSettings => ({ ...DEFAULT_MOTION_LAB, ...patch })

function snapshot(handle: MotionLabHandle) {
  handle.root.updateMatrixWorld(true)
  const result: unknown[] = []
  handle.root.traverse(object => {
    const materials = object instanceof Mesh ? (Array.isArray(object.material) ? object.material : [object.material]) : []
    result.push([object.name, object.type, object.visible, [...object.matrixWorld.elements], materials.map(material =>
      material instanceof MeshStandardMaterial ? [material.color.getHex(), material.emissive.getHex(), material.emissiveIntensity, material.opacity] : material.type)])
  })
  return result
}

function resources(root: Object3D) {
  const geometries = new Set<Mesh['geometry']>(), materials = new Set<MeshStandardMaterial>()
  root.traverse(object => {
    if (!(object instanceof Mesh)) return
    geometries.add(object.geometry)
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material as MeshStandardMaterial)
  })
  return { geometries, materials }
}

for (const [name, build] of Object.entries(builders)) {
  test(`${name}: seeking, seed, speed and solid bounds are deterministic without a renderer`, () => {
    const input = settings(), before = structuredClone(input), a = build(input), b = build(settings()), fast = build(settings({ speed: 2 }))
    try {
      a.update(6); b.update(6); fast.update(3)
      const pose = snapshot(a)
      assert.deepEqual(snapshot(b), pose, 'independently built copies have the same geometry pose and materials')
      assert.deepEqual(snapshot(fast), pose, 'speed samples the same absolute scene time')
      for (const t of [0, 24, 100, 1, 6]) a.update(t)
      assert.deepEqual(snapshot(a), pose, 'out-of-order export frames must not accumulate motion or colors')
      const { geometries, materials } = resources(a.root)
      assert.ok(geometries.size > 3 && materials.size > 5)
      let meshCount = 0
      a.root.traverse(object => {
        assert.ok(object.matrixWorld.elements.every(Number.isFinite), object.name)
        if (!(object instanceof Mesh)) return
        meshCount++
        object.geometry.computeBoundingBox()
        const size = object.geometry.boundingBox!.getSize(new Vector3())
        assert.ok(size.x > 0 && size.y > 0 && size.z > 0, `${object.name} is a solid, not a plane`)
        assert.ok(object.scale.x > 0 && object.scale.y > 0 && object.scale.z > 0)
      })
      assert.ok(meshCount > 60 && meshCount < 650, `bounded native detail: ${meshCount} meshes`)
      const box = new Box3().setFromObject(a.root), size = box.getSize(new Vector3())
      assert.ok(size.x > 5 && size.y > 2 && size.z > 5)
      assert.ok([...box.min.toArray(), ...box.max.toArray()].every(value => Number.isFinite(value) && Math.abs(value) < 60))
      assert.deepEqual(input, before, 'building or animating never mutates shared settings')
    } finally { a.dispose(); b.dispose(); fast.dispose() }
  })

  test(`${name}: different seeds change scenery; disposal is exact and isolated`, () => {
    const a = build(settings()), sibling = build(settings({ seed: 381 }))
    a.update(11); sibling.update(11)
    assert.notDeepEqual(snapshot(a), snapshot(sibling))
    const siblingBefore = snapshot(sibling), own = resources(a.root), others = resources(sibling.root)
    const counts = new Map<object, number>()
    for (const resource of [...own.geometries, ...own.materials]) {
      assert.ok(!others.geometries.has(resource as Mesh['geometry']) && !others.materials.has(resource as MeshStandardMaterial))
      counts.set(resource, 0)
      resource.addEventListener('dispose', () => counts.set(resource, counts.get(resource)! + 1))
    }
    a.dispose(); a.dispose()
    assert.equal(a.root.children.length, 0)
    assert.ok([...counts.values()].every(count => count === 1), 'shared geometry is released once, even on a second dispose')
    assert.deepEqual(snapshot(sibling), siblingBefore, 'another set retains all geometry, materials and animation')
    sibling.update(12); assert.notDeepEqual(snapshot(sibling), siblingBefore)
    sibling.dispose()
  })
}

test('flight has two original aircraft with independent propellers, route, pitch and bank', () => {
  const scene = buildSunsetFlight(settings())
  try {
    const lead = scene.root.getObjectByName('lead-aircraft')!, wingman = scene.root.getObjectByName('wingman-aircraft')!
    const start = lead.position.clone(), bank = lead.rotation.x
    scene.update(8)
    assert.notDeepEqual(lead.position.toArray(), start.toArray())
    assert.notEqual(lead.rotation.x, bank)
    assert.notEqual(lead.rotation.z, 0)
    assert.notDeepEqual(lead.position.toArray(), wingman.position.toArray())
    assert.notEqual(lead.getObjectByName('propeller')!.rotation.x, wingman.getObjectByName('propeller')!.rotation.x)
    for (const t of [2, 8, 13, 23]) {
      scene.update(t)
      const forward = new Vector3(1, 0, 0).applyQuaternion(lead.quaternion).setY(0).normalize()
      const tangent = new Vector3(3.4 * Math.cos(t * .19), 0, -2.5 * Math.sin(t * .19)).normalize()
      assert.ok(forward.dot(tangent) > .999, 'bank is local: it must not turn the nose away from the flight path')
    }
  } finally { scene.dispose() }
})

test('carriage retains a still interior while volumetric scenery scrolls through four seasons', () => {
  const scene = buildSeasonalCarriage(settings())
  try {
    const tree = scene.root.getObjectByName('landscape-tree-0')!, table = scene.root.getObjectByName('tabletop')!
    const tableBefore = table.position.toArray(), treeBefore = tree.position.x, colors = []
    for (const [index, season] of ['spring', 'summer', 'autumn', 'winter'].entries()) {
      scene.update(index * 8)
      assert.equal(scene.root.userData.season, season)
      colors.push((scene.root.getObjectByName('seasonal-canopy') as Mesh<never, MeshStandardMaterial>).material.color.getHex())
    }
    assert.equal(new Set(colors).size, 4)
    assert.notEqual(tree.position.x, treeBefore)
    assert.deepEqual(table.position.toArray(), tableBefore)
    assert.equal(scene.root.getObjectByName('winter-snow')!.visible, true)
    scene.update(0)
    assert.equal(scene.root.getObjectByName('winter-snow')!.visible, false)
    assert.ok(scene.root.getObjectByName('window-glass') && scene.root.getObjectByName('cup-thick-wall') && scene.root.getObjectByName('lamp-shade'))
  } finally { scene.dispose() }
})

test('data assembly tours actual racks, assembles and explodes the processor around its cooling hardware', () => {
  const scene = buildDataAssembly(settings())
  try {
    const layer = scene.root.getObjectByName('assembly-layer-5')!, tour = scene.root.getObjectByName('data-center-tour')!
    scene.update(8); const assembled = layer.position.y, before = tour.rotation.y
    assert.equal(scene.root.userData.assemblyPhase, 'running')
    scene.update(24)
    assert.equal(scene.root.userData.assemblyPhase, 'inspection')
    assert.ok(layer.position.y > assembled + 2)
    assert.notEqual(tour.rotation.y, before)
    assert.ok(scene.root.getObjectByName('liquid-cooling-radiator') && scene.root.getObjectByName('heatsink-fin') && scene.root.getObjectByName('data-packet'))
  } finally { scene.dispose() }
})

test('the keeper climbs physical stairs before the lighthouse beam starts rotating', () => {
  const scene = buildLighthouseStory(settings())
  try {
    const keeper = scene.root.getObjectByName('lighthouse-keeper')!, beacon = scene.root.getObjectByName('rotating-beacon')!
    const light = scene.root.getObjectByName('lighthouse-light-volume')!
    scene.update(2); const bottom = keeper.position.y
    scene.update(10); const halfway = keeper.position.y
    assert.ok(halfway > bottom)
    assert.equal(beacon.rotation.y, 0); assert.equal(light.visible, false)
    scene.update(18); assert.ok(keeper.position.y > halfway)
    assert.equal(light.visible, false)
    scene.update(25); assert.ok(beacon.rotation.y > 0); assert.equal(light.visible, true)
    scene.update(0); assert.equal(light.visible, false)
    assert.ok(scene.root.getObjectByName('spiral-stair-tread') && scene.root.getObjectByName('keepers-cottage'))
  } finally { scene.dispose() }
})

test('extreme supported motion settings stay finite and bounded throughout long exports', () => {
  for (const build of Object.values(builders)) {
    const scene = build(settings({ amplitude: 3, speed: 3, density: 3000, seed: 2147483647 }))
    try {
      for (const t of [-2, 0, 3, 10, 32, 180, 10000]) {
        scene.update(t); snapshot(scene)
        const bounds = new Box3().setFromObject(scene.root)
        assert.ok([...bounds.min.toArray(), ...bounds.max.toArray()].every(value => Number.isFinite(value) && Math.abs(value) < 60))
      }
    } finally { scene.dispose() }
  }
})
