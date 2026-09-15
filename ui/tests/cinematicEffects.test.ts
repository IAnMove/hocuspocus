import assert from 'node:assert/strict'
import { test } from 'node:test'
import { BoxGeometry, Mesh, MeshBasicMaterial, MeshStandardMaterial, Scene } from 'three'
import { effectsTemplateDocument } from '../src/features/scene3d/effectsTemplates'
import { parseScene3DDocument } from '../src/features/scene3d/document'
import { MaterializationRuntime } from '../src/features/scene3d/materialization'
import { WORLD_SFX_KINDS, parseWorldSfx } from '../src/features/sceneFx/world'
import { syncWorldSfx } from '../src/features/sceneFx/worldRuntime'

test('cinematic templates roundtrip their environment, appearance and native animation', () => {
  for (const id of ['reflective-stage', 'character-materialization']) {
    const doc = effectsTemplateDocument(id)!, parsed = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!
    assert.equal(parsed.templateId, id); assert.deepEqual(parsed.environment, doc.environment)
    assert.deepEqual(parsed.slots[0].appearance, doc.slots[0].appearance)
    assert.equal(parsed.slots[0].clip?.name, 'Walking'); assert.equal(parsed.slots[0].performance, 'idle')
    assert.equal(parsed.slots[1].surface, 'environment'); assert.ok(parsed.worldSfx?.some(c => c.kind === 'smoke'))
  }
})
test('arrival composes existing shaders, seeks backwards and restores lit and unlit materials', () => {
  for (const material of [new MeshBasicMaterial(), new MeshStandardMaterial()]) {
    let calls = 0
    const previous = () => { calls++ }; material.onBeforeCompile = previous
    const root = new Mesh(new BoxGeometry(), material), runtime = new MaterializationRuntime()
    const appearance = { start: 2, duration: 1, color: '#83e8ff' }
    runtime.sync(root, appearance, 2.5)
    const shader = { uniforms: {}, vertexShader: '#include <common>\n#include <project_vertex>', fragmentShader: '#include <common>\n#include <alphatest_fragment>\n#include <opaque_fragment>' }
    material.onBeforeCompile(shader as never, {} as never)
    assert.equal(calls, 1); assert.match(shader.fragmentShader, /discard/)
    const uniforms = shader.uniforms as { arrivalCut: { value: number } }, midpoint = uniforms.arrivalCut.value
    runtime.sync(root, appearance, 4); assert.ok(uniforms.arrivalCut.value > midpoint)
    runtime.sync(root, appearance, 2.5); assert.equal(uniforms.arrivalCut.value, midpoint)
    runtime.sync(root, appearance, 0); assert.equal(root.visible, false)
    runtime.sync(root, undefined, 0); assert.equal(root.visible, true); assert.equal(material.onBeforeCompile, previous)
  }
})
test('all spatial kinds seek deterministically, lightning responds to intensity and nodes release', () => {
  const scene = new Scene(), nodes = new Map()
  const cues = parseWorldSfx(WORLD_SFX_KINDS.map((kind, i) => ({ id: String(i), kind, start: 1, end: 4, seed: i })))
  syncWorldSfx(scene, nodes, cues, 2, [])
  const lightning = [...nodes.values()].find(n => n.kind === 'lightning').root
  const bolt = lightning.children.find((c: Mesh) => c.userData.kind === 'bolt').children[0]
  const before = bolt.material.color.clone()
  syncWorldSfx(scene, nodes, cues.map(c => ({ ...c, intensity: c.intensity / 2 })), 2, []); assert.ok(bolt.material.color.r < before.r)
  syncWorldSfx(scene, nodes, cues, 2, []); assert.deepEqual(bolt.material.color, before)
  const path = lightning.children.map((c: Mesh) => c.position.toArray())
  syncWorldSfx(scene, nodes, cues, 3, []); syncWorldSfx(scene, nodes, cues, 2, [])
  assert.deepEqual(lightning.children.map((c: Mesh) => c.position.toArray()), path)
  syncWorldSfx(scene, nodes, cues, 0, []); assert.ok([...nodes.values()].every(n => !n.root.visible))
  syncWorldSfx(scene, nodes, [], 0, []); assert.equal(nodes.size, 0); assert.equal(scene.children.length, 0)
})
