import test from 'node:test'
import assert from 'node:assert/strict'
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshStandardMaterial, Texture } from 'three'
import { ATLAS_KEY, applyAtlasProjection, patchAtlasShader, readAtlasFrame } from '../src/features/scene3d/atlasProjection.ts'

test('the frame comes from the material extras and anything malformed is refused', () => {
  assert.deepEqual(readAtlasFrame({ atlas: { body: [0, 0.9, 2], head: [1.7, 0.4, 1.5] } }), { body: [0, 0.9, 2], head: [1.7, 0.4, 1.5] })
  assert.deepEqual(readAtlasFrame({ atlas: { body: [0, 0.9, 2] } }), { body: [0, 0.9, 2] })
  assert.deepEqual(readAtlasFrame({ atlas: { body: [0, 0.9, 2], skin: [0.8, 0.6, 0.5] } }), { body: [0, 0.9, 2], skin: [0.8, 0.6, 0.5] })
  assert.equal(readAtlasFrame({ atlas: { body: [0, 0.9, 2], skin: [2, 0, 0] } })?.skin, undefined, 'a colour outside 0..1 is refused')
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
  assert.ok(shader.fragmentShader.includes('uniform vec3 atlasSkin;') && shader.fragmentShader.includes('underside'), 'the jaw underside takes the skin colour')
  assert.ok(shader.fragmentShader.includes('uniform float atlasFaceOnly;') && shader.fragmentShader.includes('faceYaw'), 'every uniform the shader reads is declared')
  assert.ok(shader.fragmentShader.includes('uniform vec3 atlasBody;') && shader.fragmentShader.includes('diffuseColor *= sampledDiffuseColor;'))
  assert.ok(!shader.fragmentShader.includes('#include <map_fragment>'))
  assert.deepEqual(shader.uniforms.atlasBody.value.toArray(), [0, 0.9, 2])
  assert.deepEqual(shader.uniforms.atlasHead.value.toArray(), [1.7, 0.4, 1.5])
})

test('the head blend can split tones from fine texture, and the split is only read when valid', () => {
  assert.equal(readAtlasFrame({ atlas: { body: [0, 1, 2], bandDetail: 0.5 } })?.bandDetail, 0.5)
  assert.equal(readAtlasFrame({ atlas: { body: [0, 1, 2], bandDetail: 3 } })?.bandDetail, undefined)
  const shader = {
    uniforms: {},
    vertexShader: '#include <common>\nvoid main() {\n#include <begin_vertex>\n}',
    fragmentShader: '#include <common>\n#include <map_pars_fragment>\nvoid main() {\n#include <map_fragment>\n}',
  }
  patchAtlasShader(shader, { body: [0, 0.9, 2], head: [1.7, 0.4, 1.5], bandDetail: 0 })
  assert.ok(shader.fragmentShader.includes('uniform float atlasBand;') && shader.fragmentShader.includes('uniform float atlasDetail;'), 'the split uniforms are declared')
  assert.ok(shader.fragmentShader.includes('vec4 atlasLow(') && shader.fragmentShader.includes('textureLod'), 'the tones come from a mip level of the picture')
  assert.equal(shader.uniforms.atlasBand.value, 1)
  assert.equal(shader.uniforms.atlasDetail.value, 0)
  const plain = { uniforms: {}, vertexShader: '', fragmentShader: '#include <common>\n#include <map_fragment>' }
  patchAtlasShader(plain, { body: [0, 0.9, 2] })
  assert.equal(plain.uniforms.atlasBand.value, 0, 'frames without the split keep the plain blend')
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
