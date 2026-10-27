import test from 'node:test'
import assert from 'node:assert/strict'
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshStandardMaterial, Texture } from 'three'
import { ATLAS_KEY, applyAtlasProjection, patchAtlasShader, readAtlasFrame } from '../src/features/scene3d/atlasProjection.ts'

test('the frame comes from the material extras and anything malformed is refused', () => {
  assert.deepEqual(readAtlasFrame({ atlas: { body: [0, 0.9, 2], head: [1.7, 0.4, 1.5] } }), { body: [0, 0.9, 2], head: [1.7, 0.4, 1.5] })
  assert.deepEqual(readAtlasFrame({ atlas: { body: [0, 0.9, 2] } }), { body: [0, 0.9, 2] })
  assert.equal(readAtlasFrame({ atlas: { body: [0, 0.9] } }), undefined)
  assert.equal(readAtlasFrame({ atlas: { body: [0, 0.9, 0] } }), undefined)
  assert.equal(readAtlasFrame({ atlas: { body: [0, 'a', 1] } }), undefined)
  assert.equal(readAtlasFrame({}), undefined)
})

test('the shader samples the atlas from the bind pose and blends the views by the normal', () => {
  const shader = {
    uniforms: {},
    vertexShader: '#include <common>\nvoid main() {\n#include <begin_vertex>\n}',
    fragmentShader: '#include <common>\nvoid main() {\n#include <map_fragment>\n}',
  }
  patchAtlasShader(shader, { body: [0, 0.9, 2], head: [1.7, 0.4, 1.5] })
  assert.ok(shader.vertexShader.includes('vAtlasPos = position;') && shader.vertexShader.includes('vAtlasNormal = normal;'))
  assert.ok(shader.fragmentShader.includes('uniform float atlasFaceOnly;') && shader.fragmentShader.includes('faceYaw'), 'every uniform the shader reads is declared')
  assert.ok(shader.fragmentShader.includes('uniform vec3 atlasBody;') && shader.fragmentShader.includes('diffuseColor *= sampledDiffuseColor;'))
  assert.ok(!shader.fragmentShader.includes('#include <map_fragment>'))
  assert.deepEqual(shader.uniforms.atlasBody.value.toArray(), [0, 0.9, 2])
  assert.deepEqual(shader.uniforms.atlasHead.value.toArray(), [1.7, 0.4, 1.5])
})

test('only textured materials with an atlas frame are draped', () => {
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(new Float32Array(9), 3))
  const draped = new MeshStandardMaterial({ name: 'body', map: new Texture() })
  draped.userData.atlas = { body: [0, 0.9, 2] }
  const plain = new MeshStandardMaterial({ name: 'hair', map: new Texture() })
  const bare = new MeshStandardMaterial({ name: 'face' })
  bare.userData.atlas = { body: [0, 0.9, 2] }
  const group = new Group()
  group.add(new Mesh(geometry, [draped, plain, bare]))
  applyAtlasProjection(group)
  assert.equal(draped.customProgramCacheKey(), ATLAS_KEY)
  assert.notEqual(plain.customProgramCacheKey(), ATLAS_KEY)
  assert.notEqual(bare.customProgramCacheKey(), ATLAS_KEY)
})
