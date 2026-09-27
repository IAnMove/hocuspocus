import assert from 'node:assert/strict'
import test from 'node:test'
import { demoShip } from '../src/features/sceneTemplates/demoShips.ts'

const DATA_PREFIX = 'data:model/gltf-binary;base64,'
const GLB_MAGIC = 0x46546c67
const JSON_CHUNK = 0x4e4f534a
const BIN_CHUNK = 0x004e4942
const COMPONENT_BYTES = { 5126: 4 }
const COMPONENTS = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 }

test('demo ships fail closed on unknown runtime variants', () => {
  for (const variant of ['blue', '', null, 1, {}]) {
    assert.throws(() => demoShip(variant), /variant/i)
  }
})

const decodeGlb = asset => {
  assert.equal(asset.type, 'model3d')
  assert.ok(asset.source.startsWith(DATA_PREFIX))
  assert.doesNotMatch(asset.source, /https?:\/\/|\/api\/|blob:/i)
  const bytes = Buffer.from(asset.source.slice(DATA_PREFIX.length), 'base64')
  assert.ok(bytes.length < 2 * 1024 * 1024, `${asset.name} must stay below the 2 MiB demo cap`)
  assert.ok(bytes.length >= 28)
  const header = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  assert.equal(header.getUint32(0, true), GLB_MAGIC)
  assert.equal(header.getUint32(4, true), 2)
  assert.equal(header.getUint32(8, true), bytes.length)

  const jsonLength = header.getUint32(12, true)
  assert.equal(jsonLength % 4, 0)
  assert.equal(header.getUint32(16, true), JSON_CHUNK)
  const jsonStart = 20
  const jsonEnd = jsonStart + jsonLength
  assert.ok(jsonEnd + 8 <= bytes.length)
  const jsonText = new TextDecoder().decode(bytes.subarray(jsonStart, jsonEnd)).trim()
  const json = JSON.parse(jsonText)
  const binLength = header.getUint32(jsonEnd, true)
  assert.equal(binLength % 4, 0)
  assert.equal(header.getUint32(jsonEnd + 4, true), BIN_CHUNK)
  const binStart = jsonEnd + 8
  assert.equal(binStart + binLength, bytes.length)
  assert.equal(json.buffers?.length, 1)
  assert.equal(json.buffers[0].byteLength, binLength)
  return { json, binary: bytes.subarray(binStart, binStart + binLength) }
}

const assertFiniteBounds = (accessor, label) => {
  assert.equal(accessor.min?.length, accessor.max?.length, `${label} has paired bounds`)
  for (let index = 0; index < accessor.min.length; index += 1) {
    assert.ok(Number.isFinite(accessor.min[index]), `${label} min is finite`)
    assert.ok(Number.isFinite(accessor.max[index]), `${label} max is finite`)
    assert.ok(accessor.min[index] <= accessor.max[index], `${label} min <= max`)
  }
}

const assertValidGeometry = ({ json, binary }, name) => {
  assert.ok(Array.isArray(json.meshes) && json.meshes.length > 0, `${name} has a mesh`)
  assert.ok(Array.isArray(json.bufferViews) && json.bufferViews.length > 0, `${name} has buffer views`)
  assert.ok(Array.isArray(json.accessors) && json.accessors.length > 0, `${name} has accessors`)
  for (const [index, view] of json.bufferViews.entries()) {
    const offset = view.byteOffset ?? 0
    assert.equal(view.buffer, 0)
    assert.equal(offset % 4, 0, `bufferView ${index} is aligned`)
    assert.equal(view.byteLength % 4, 0, `bufferView ${index} length is aligned`)
    assert.ok(offset >= 0 && offset + view.byteLength <= binary.length, `bufferView ${index} is inside BIN`)
  }
  for (const [index, accessor] of json.accessors.entries()) {
    assert.equal(accessor.componentType, 5126, `accessor ${index} uses float32`)
    assert.ok(COMPONENT_BYTES[accessor.componentType])
    assert.equal(accessor.type, 'VEC3')
    assert.equal(COMPONENTS[accessor.type], 3)
    assert.ok(Number.isInteger(accessor.count) && accessor.count > 0)
    assertFiniteBounds(accessor, `accessor ${index}`)
    const view = json.bufferViews[accessor.bufferView]
    assert.ok(view)
    const accessorOffset = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0)
    const byteLength = accessor.count * COMPONENTS[accessor.type] * COMPONENT_BYTES[accessor.componentType]
    assert.equal(accessorOffset % 4, 0, `accessor ${index} is aligned`)
    assert.ok(accessorOffset + byteLength <= (view.byteOffset ?? 0) + view.byteLength, `accessor ${index} fits its view`)
    const values = new Float32Array(binary.buffer, binary.byteOffset + accessorOffset, accessor.count * 3)
    for (const value of values) assert.ok(Number.isFinite(value), `accessor ${index} contains finite geometry`)
  }
  for (const [meshIndex, mesh] of json.meshes.entries()) {
    assert.ok(mesh.primitives?.length, `mesh ${meshIndex} has primitives`)
    for (const primitive of mesh.primitives) {
      assert.ok(Number.isInteger(primitive.attributes.POSITION))
      assert.ok(Number.isInteger(primitive.attributes.NORMAL))
      assert.ok(json.accessors[primitive.attributes.POSITION])
      assert.ok(json.accessors[primitive.attributes.NORMAL])
      assert.ok(Number.isInteger(primitive.material))
      assert.ok(json.materials[primitive.material])
    }
  }
}

test('coral and teal demo ships are valid aligned glTF 2.0 GLB data URIs', () => {
  for (const variant of ['coral', 'teal']) assertValidGeometry(decodeGlb(demoShip(variant)), variant)
})

test('demo ships are deterministic, visibly different variants, and remain below the asset cap', () => {
  const coralA = demoShip('coral')
  const coralB = demoShip('coral')
  const teal = demoShip('teal')
  assert.deepEqual(coralA, coralB)
  assert.notEqual(coralA.source, teal.source)
  assert.notEqual(coralA.name, teal.name)
  assert.ok(coralA.source.length < 3 * 1024 * 1024)
  assert.ok(teal.source.length < 3 * 1024 * 1024)
})
