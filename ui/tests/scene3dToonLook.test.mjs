import assert from 'node:assert/strict'
import test from 'node:test'
import {
  BackSide, Bone, Box3, BoxGeometry, BufferAttribute, DataTexture, DoubleSide, Group, Mesh, MeshBasicMaterial,
  MeshLambertMaterial, MeshPhongMaterial, MeshPhysicalMaterial, MeshStandardMaterial, MeshToonMaterial, NearestFilter,
  Raycaster, Scene, ShaderChunk, ShaderLib, Skeleton, SkinnedMesh, Texture, UniformsUtils, Vector3,
} from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { setUiLanguage } from '../src/i18n/index.ts'
import { RenderLookControls } from '../src/features/scene3d/CinematicControls.tsx'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import {
  DEFAULT_TOON, INK_FRAGMENT, INK_VERTEX, OUTLINE_NORMAL, ToonLook, environmentFill, inkMaterial, isInkHull, outlineNormals,
  resolveToon,
} from '../src/features/scene3d/toonLook.ts'

/** What three hands onBeforeCompile for a toon material, before includes are resolved. */
function toonShader() {
  return { uniforms: UniformsUtils.clone(ShaderLib.toon.uniforms), vertexShader: ShaderLib.toon.vertexShader, fragmentShader: ShaderLib.toon.fragmentShader }
}

/** A binary glTF like a Hunyuan3D export: positions and UVs, no normals, an untextured PBR material. */
function normalLessGlb() {
  const positions = new Float32Array([-1, 0, 0, 1, 0, 0, 0, 2, 0, 0, 1, 1])
  const uvs = new Float32Array([0, 0, 1, 0, .5, 1, .5, .5])
  const indices = new Uint16Array([0, 1, 2, 0, 2, 3, 1, 3, 2, 0, 3, 1])
  const bin = Buffer.concat([Buffer.from(positions.buffer), Buffer.from(uvs.buffer), Buffer.from(indices.buffer)])
  const json = {
    asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, TEXCOORD_0: 1 }, indices: 2, material: 0 }] }],
    materials: [{ pbrMetallicRoughness: { baseColorFactor: [0.8, 0.5, 0.2, 1], roughnessFactor: 0.9 } }],
    buffers: [{ byteLength: bin.length }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: 48 }, { buffer: 0, byteOffset: 48, byteLength: 32 }, { buffer: 0, byteOffset: 80, byteLength: 24 }],
    accessors: [
      { bufferView: 0, componentType: 5126, count: 4, type: 'VEC3', min: [-1, 0, 0], max: [1, 2, 1] },
      { bufferView: 1, componentType: 5126, count: 4, type: 'VEC2' },
      { bufferView: 2, componentType: 5123, count: 12, type: 'SCALAR' },
    ],
  }
  let text = Buffer.from(JSON.stringify(json))
  text = Buffer.concat([text, Buffer.alloc(-text.length % 4 & 3, 0x20)])
  const header = Buffer.alloc(12), jsonHead = Buffer.alloc(8), binHead = Buffer.alloc(8)
  header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4); header.writeUInt32LE(12 + 8 + text.length + 8 + bin.length, 8)
  jsonHead.writeUInt32LE(text.length, 0); jsonHead.writeUInt32LE(0x4e4f534a, 4)
  binHead.writeUInt32LE(bin.length, 0); binHead.writeUInt32LE(0x004e4942, 4)
  const glb = Buffer.concat([header, jsonHead, text, binHead, bin])
  return glb.buffer.slice(glb.byteOffset, glb.byteOffset + glb.length)
}

const settings = { ...DEFAULT_TOON }

function drawn(look, inspect) {
  let seen = false
  look.draw(() => { inspect(); seen = true })
  assert.ok(seen, 'the render callback runs')
}

function skinnedBox() {
  const geometry = new BoxGeometry(1, 2, 1, 1, 2, 1)
  const count = geometry.getAttribute('position').count
  const indices = new Uint16Array(count * 4), weights = new Float32Array(count * 4)
  for (let i = 0; i < count; i += 1) {
    indices[i * 4] = geometry.getAttribute('position').getY(i) > 0 ? 1 : 0
    weights[i * 4] = 1
  }
  geometry.setAttribute('skinIndex', new BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new BufferAttribute(weights, 4))
  geometry.morphAttributes.position = [new BufferAttribute(new Float32Array(count * 3), 3)]
  const root = new Bone(), tip = new Bone()
  tip.position.y = 1
  root.add(tip)
  const mesh = new SkinnedMesh(geometry, new MeshStandardMaterial({ map: new Texture() }))
  mesh.name = 'Body'
  mesh.add(root)
  mesh.bind(new Skeleton([root, tip]))
  mesh.morphTargetInfluences = [0.4]
  mesh.morphTargetDictionary = { smile: 0 }
  return mesh
}

test('the toon look survives persistence with bounded settings and unknown looks are refused', () => {
  const doc = { ...createDefaultScene3DDocument(), renderLook: 'toon', toon: { steps: 9, outline: -2, ink: '#ABCDEF' } }
  const parsed = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.equal(parsed.renderLook, 'toon')
  assert.deepEqual(parsed.toon, { steps: 4, outline: 0, ink: '#abcdef' })
  assert.deepEqual(parseScene3DDocument({ ...doc, toon: { steps: 'many', outline: 2.346, ink: 'red' } }).toon, { outline: 2.35 })
  assert.equal(parseScene3DDocument({ ...doc, toon: 'thick' }).toon, undefined)
  assert.equal(parseScene3DDocument({ ...doc, renderLook: 'n64' }).renderLook, 'n64')
  assert.equal(parseScene3DDocument({ ...doc, renderLook: 'cel' }), null)
  assert.equal(parseScene3DDocument({ ...doc, renderLook: 'unknown' }), null)
  assert.deepEqual(resolveToon({ renderLook: 'toon' }), DEFAULT_TOON)
  assert.deepEqual(resolveToon({ renderLook: 'toon', toon: { steps: 2, ink: '#ff0000' } }), { steps: 2, outline: DEFAULT_TOON.outline, ink: '#ff0000' })
  assert.equal(resolveToon({ renderLook: 'n64', toon: { steps: 2 } }), null)
  assert.equal(resolveToon(createDefaultScene3DDocument()), null)
})

test('lit model materials become toon copies only while drawing and keep maps, colours, alpha and side', () => {
  const map = new Texture(), emissiveMap = new Texture(), alphaMap = new Texture()
  const standard = new MeshStandardMaterial({ map, color: '#3366aa', emissive: '#110000', emissiveMap, emissiveIntensity: 2,
    alphaMap, transparent: true, opacity: .5, side: DoubleSide, vertexColors: true })
  const others = [new MeshPhysicalMaterial({ color: '#00ff00' }), new MeshLambertMaterial({ map }), new MeshPhongMaterial({ color: '#ff00ff' })]
  const unlit = new MeshBasicMaterial({ map })
  const root = new Group()
  const meshes = [standard, ...others, unlit].map(material => {
    const mesh = new Mesh(new BoxGeometry(), material)
    root.add(mesh)
    return mesh
  })
  const look = new ToonLook()
  look.sync(settings, [{ root, outline: false }])
  drawn(look, () => {
    const toon = meshes[0].material
    assert.ok(toon instanceof MeshToonMaterial)
    assert.equal(toon.map, map)
    assert.equal(toon.emissiveMap, emissiveMap)
    assert.equal(toon.alphaMap, alphaMap)
    assert.ok(toon.color.equals(standard.color))
    assert.ok(toon.emissive.equals(standard.emissive))
    assert.equal(toon.emissiveIntensity, 2)
    assert.equal(toon.transparent, true)
    assert.equal(toon.opacity, .5)
    assert.equal(toon.side, DoubleSide)
    assert.equal(toon.vertexColors, true)
    assert.ok(toon.gradientMap instanceof DataTexture)
    assert.equal(toon.gradientMap.image.width, 3)
    assert.equal(toon.gradientMap.magFilter, NearestFilter)
    assert.equal(toon.gradientMap.minFilter, NearestFilter)
    for (const [index, source] of others.entries()) {
      assert.ok(meshes[index + 1].material instanceof MeshToonMaterial)
      assert.ok(meshes[index + 1].material.color.equals(source.color))
    }
    assert.equal(meshes[1 + others.length].material, unlit, 'unlit materials are already flat')
  })
  assert.deepEqual(meshes.map(mesh => mesh.material), [standard, ...others, unlit])
  // Runtime changes on the authored material reach the next draw.
  standard.opacity = .25
  standard.map = null
  standard.needsUpdate = true
  drawn(look, () => {
    assert.equal(meshes[0].material.opacity, .25)
    assert.equal(meshes[0].material.map, null)
  })
  look.dispose()
})

test('image cutouts and objects outside the model roots keep their authored material', () => {
  const scene = new Scene()
  const model = new Group()
  model.add(new Mesh(new BoxGeometry(), new MeshStandardMaterial()))
  const cutoutMaterial = new MeshStandardMaterial({ map: new Texture(), transparent: true })
  const cutout = new Mesh(new BoxGeometry(), cutoutMaterial)
  scene.add(model, cutout)
  const look = new ToonLook()
  look.sync(settings, [{ root: model, outline: true }])
  drawn(look, () => {
    assert.ok(model.children[0].material instanceof MeshToonMaterial)
    assert.equal(cutout.material, cutoutMaterial)
    assert.equal(cutout.children.length, 0)
  })
  look.dispose()
})

test('the ink hull shares geometry, skeleton and morph weights and never reaches picking or bounds', () => {
  const mesh = skinnedBox()
  const root = new Group()
  root.add(mesh)
  root.scale.setScalar(.01)
  root.updateMatrixWorld(true)
  const bounds = new Box3().setFromObject(root, true)
  const look = new ToonLook()
  look.sync(settings, [{ root, outline: true }])
  drawn(look, () => {
    const hull = mesh.children.find(isInkHull)
    assert.ok(hull, 'the skinned mesh carries an ink hull while drawing')
    assert.equal(hull.isSkinnedMesh, true)
    assert.equal(hull.skeleton, mesh.skeleton)
    assert.ok(hull.bindMatrix.equals(mesh.bindMatrix))
    assert.equal(hull.bindMode, mesh.bindMode)
    assert.equal(hull.geometry, mesh.geometry)
    assert.equal(hull.morphTargetInfluences, mesh.morphTargetInfluences)
    assert.equal(hull.morphTargetDictionary, mesh.morphTargetDictionary)
    assert.notEqual(hull.name, mesh.name, 'animation tracks keep binding to the authored mesh')
    assert.equal(hull.castShadow, false)
    assert.equal(hull.material.side, BackSide)
    assert.ok(mesh.geometry.getAttribute(OUTLINE_NORMAL))
    root.updateMatrixWorld(true)
    const hits = new Raycaster(new Vector3(0, .005, 5), new Vector3(0, 0, -1)).intersectObject(root, true)
    assert.ok(hits.length > 0)
    assert.ok(hits.every(hit => !isInkHull(hit.object)))
  })
  assert.equal(mesh.children.some(isInkHull), false)
  assert.ok(new Box3().setFromObject(root, true).equals(bounds))
  // A later bind (another rig, the same mesh) is followed.
  const other = new Skeleton([new Bone(), new Bone()])
  mesh.bind(other)
  drawn(look, () => assert.equal(mesh.children.find(isInkHull).skeleton, other))
  look.dispose()
})

test('transparent, alpha-cut and hidden materials get no ink; array materials hide those groups', () => {
  const opaque = new MeshStandardMaterial()
  const glass = new MeshStandardMaterial({ transparent: true, opacity: .4 })
  const cards = new MeshStandardMaterial({ alphaTest: .5 })
  const geometry = new BoxGeometry()
  const mixed = new Mesh(geometry, [opaque, glass, opaque, cards, new MeshBasicMaterial({ visible: false }), opaque])
  const onlyGlass = new Mesh(new BoxGeometry(), glass)
  const root = new Group()
  root.add(mixed, onlyGlass)
  const look = new ToonLook()
  look.sync(settings, [{ root, outline: true }])
  drawn(look, () => {
    const hull = mixed.children.find(isInkHull)
    assert.deepEqual(hull.material.map(material => material.visible), [true, false, true, false, false, true])
    assert.equal(onlyGlass.children.some(isInkHull), false)
  })
  look.sync({ ...settings, outline: 0 }, [{ root, outline: true }])
  drawn(look, () => assert.equal(mixed.children.some(isInkHull), false, 'width 0 draws no line'))
  look.sync(settings, [{ root, outline: false }])
  drawn(look, () => {
    assert.equal(mixed.children.some(isInkHull), false, 'a materializing model has no ink')
    assert.ok(mixed.material[0] instanceof MeshToonMaterial)
  })
  look.dispose()
})

test('one welded outline normal per corner keeps the hull closed over hard edges', () => {
  const geometry = new BoxGeometry(2, 2, 2)
  const normals = outlineNormals(geometry)
  assert.equal(outlineNormals(geometry), normals, 'computed once per geometry')
  const position = geometry.getAttribute('position')
  assert.equal(position.count, 24, 'a box splits each corner into three vertices')
  for (let i = 0; i < position.count; i += 1) {
    const corner = new Vector3().fromBufferAttribute(position, i).normalize()
    const normal = new Vector3().fromBufferAttribute(normals, i)
    assert.ok(normal.distanceTo(corner) < 1e-5, `vertex ${i} points out of its corner`)
  }
  // A non-indexed mesh with a hard edge: both copies of the shared edge get the same normal.
  const flat = new BoxGeometry(1, 1, 1).toNonIndexed()
  const flatNormals = outlineNormals(flat)
  const flatPosition = flat.getAttribute('position')
  for (let i = 0; i < flatPosition.count; i += 1) {
    const corner = new Vector3().fromBufferAttribute(flatPosition, i).normalize()
    assert.ok(new Vector3().fromBufferAttribute(flatNormals, i).distanceTo(corner) < 1e-5)
  }
})

test('the ink shader only uses chunks three provides', () => {
  for (const source of [INK_VERTEX, INK_FRAGMENT]) {
    for (const [, chunk] of source.matchAll(/#include <(\w+)>/g)) assert.ok(ShaderChunk[chunk], `missing chunk ${chunk}`)
  }
  assert.match(INK_FRAGMENT, /if \(inkFacing < -0\.60\) discard;/, 'hull faces turned away only show through holes')
  const ink = inkMaterial()
  assert.equal(ink.side, BackSide)
  assert.equal(ink.fog, true)
  ink.dispose()
})

test('authored shader patches run on the toon copy and changes recompile it', () => {
  const calls = []
  const source = new MeshStandardMaterial()
  source.onBeforeCompile = shader => { calls.push(shader.id) }
  source.customProgramCacheKey = () => 'face-v1'
  const mesh = new Mesh(new BoxGeometry(), source)
  const root = new Group()
  root.add(mesh)
  const look = new ToonLook()
  look.sync(settings, [{ root, outline: false }])
  let toon
  drawn(look, () => { toon = mesh.material })
  toon.onBeforeCompile({ ...toonShader(), id: 'probe' }, null)
  assert.deepEqual(calls, ['probe'])
  assert.equal(toon.customProgramCacheKey(), 'toon-fill:face-v1')
  const version = toon.version
  source.needsUpdate = true
  drawn(look, () => assert.equal(mesh.material, toon))
  assert.ok(toon.version > version)
  drawn(look, () => {})
  assert.equal(toon.version, version + 1, 'an unchanged material does not recompile')
  look.dispose()
})

test('materials no longer drawn and the look switched off are disposed', () => {
  const kept = new MeshStandardMaterial(), dropped = new MeshStandardMaterial()
  const keptMesh = new Mesh(new BoxGeometry(), kept), droppedMesh = new Mesh(new BoxGeometry(), dropped)
  const root = new Group()
  root.add(keptMesh, droppedMesh)
  const look = new ToonLook()
  look.sync(settings, [{ root, outline: true }])
  const disposed = []
  let toons, ink, gradient
  drawn(look, () => {
    toons = [keptMesh.material, droppedMesh.material]
    ink = keptMesh.children.find(isInkHull).material
    gradient = keptMesh.material.gradientMap
  })
  for (const resource of [...toons, ink, gradient]) resource.addEventListener('dispose', () => disposed.push(resource))
  root.remove(droppedMesh)
  drawn(look, () => {})
  assert.deepEqual(disposed, [toons[1]])
  look.sync({ ...settings, steps: 2 }, [{ root, outline: true }])
  drawn(look, () => assert.equal(keptMesh.material.gradientMap.image.width, 2))
  assert.ok(disposed.includes(gradient), 'a new band count replaces the gradient')
  look.sync(null, [])
  assert.ok(disposed.includes(toons[0]))
  assert.ok(disposed.includes(ink))
  drawn(look, () => assert.equal(keptMesh.material, kept, 'off: nothing is swapped'))
})

test('the editor offers the toon look and its settings in Spanish and English', async () => {
  Object.assign(globalThis, { React })
  const props = { document: { renderLook: 'toon', toon: { steps: 2 } }, disabled: false, onChange: () => {} }
  const markup = () => renderToStaticMarkup(React.createElement(RenderLookControls, props))
  try {
    await setUiLanguage('es')
    const es = markup()
    assert.match(es, /Anime \(cel\)/)
    assert.match(es, /Bandas de luz/)
    assert.match(es, /value="#141018"/)
    await setUiLanguage('en')
    const en = markup()
    assert.match(en, /Toon \/ cel/)
    assert.match(en, /Nintendo 64/)
    assert.match(en, /Ink width/)
    props.document = { renderLook: 'n64', toon: { steps: 2 } }
    assert.doesNotMatch(markup(), /Light bands/)
  } finally {
    await setUiLanguage('en')
  }
})

test('a model without normals, as GLTFLoader leaves Hunyuan3D meshes, gets smooth normals for the toon draw', async () => {
  const gltf = await new GLTFLoader().parseAsync(normalLessGlb(), '')
  const mesh = gltf.scene.getObjectByProperty('isMesh', true)
  const source = mesh.material
  assert.equal(mesh.geometry.getAttribute('normal'), undefined)
  assert.equal(source.flatShading, true, 'three draws the authored material flat; MeshToonMaterial has no such fallback')
  const look = new ToonLook()
  look.sync(settings, [{ root: gltf.scene, outline: true }])
  drawn(look, () => {
    assert.ok(mesh.material instanceof MeshToonMaterial)
    assert.notEqual(mesh.material.flatShading, true)
    const normals = mesh.geometry.getAttribute('normal')
    assert.ok(normals, 'a toon material without normals lights with NaN and the bloom blackens the frame')
    for (let i = 0; i < normals.count; i += 1) {
      const length = new Vector3().fromBufferAttribute(normals, i).length()
      assert.ok(Math.abs(length - 1) < 1e-5, `normal ${i} is a unit vector`)
    }
  })
  assert.equal(mesh.geometry.getAttribute('normal'), undefined, 'the authored geometry is left as it was')
  assert.equal(mesh.material, source)
  // Every mesh the look draws with a toon material has a normal to light with.
  const scene = new Group()
  scene.add(gltf.scene, new Mesh(new BoxGeometry(), new MeshStandardMaterial()))
  look.sync(settings, [{ root: scene, outline: false }])
  drawn(look, () => scene.traverse(object => {
    if (object.material instanceof MeshToonMaterial) assert.ok(object.geometry.getAttribute('normal'))
  }))
  look.dispose()
})

test('toon surfaces get the environment light back as flat fill', () => {
  const mesh = new Mesh(new BoxGeometry(), new MeshStandardMaterial({ color: '#8899aa', metalness: 1 }))
  const root = new Group()
  root.add(mesh)
  const look = new ToonLook()
  look.sync(settings, [{ root, outline: false }], 0.7)
  let toon
  drawn(look, () => { toon = mesh.material })
  const shader = toonShader()
  toon.onBeforeCompile(shader, null)
  for (const chunk of ['#include <common>', '#include <lights_fragment_end>']) assert.ok(ShaderLib.toon.fragmentShader.includes(chunk))
  assert.match(shader.fragmentShader, /uniform vec3 toonFill;/)
  assert.match(shader.fragmentShader, /#include <lights_fragment_end>\n\treflectedLight\.indirectDiffuse \+= toonFill \* BRDF_Lambert\( material\.diffuseColor \);/)
  assert.ok(Math.abs(shader.uniforms.toonFill.value.r - environmentFill(0.7)) < 1e-6)
  assert.ok(environmentFill(0.7) / Math.PI > 0.8, 'a white surface keeps most of the light the room gives a PBR one')
  look.sync(settings, [{ root, outline: false }], 0)
  assert.equal(shader.uniforms.toonFill.value.r, 0, 'no environment, no fill')
  look.dispose()
})
