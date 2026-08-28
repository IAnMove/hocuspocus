import assert from 'node:assert/strict'
import test from 'node:test'
import {
  EXAMPLE_SAUCER_CRUISE_RECIPE,
  SCENE_RECIPE_JSON_SCHEMA,
  buildRecipeSystemPrompt,
  compileRecipeShot,
  compileSceneRecipe,
  constrainManualRecipeToInventory,
  extractJsonObject,
  h3FramesForDuration,
  h3ResolutionForScene,
  listRecipeShots,
  parseSceneRecipe,
  parseSceneRecipeText,
  recipeAssetDuration,
} from '../src/lib/sceneRecipe.ts'

test('example saucer recipe compiles to a 4-layer scene with space-cruise motion', () => {
  const recipe = parseSceneRecipe(EXAMPLE_SAUCER_CRUISE_RECIPE)
  const scene = compileSceneRecipe(recipe, {
    stars: 'stars.png',
    saucer: 'saucer.glb',
  }, filename => `/api/v1/file/${filename}`)
  assert.equal(scene.layers.length, 4)
  assert.equal(scene.layers[0].type, 'camera')
  assert.equal(scene.layers[1].source, '/api/v1/file/stars.png')
  assert.equal(scene.layers[2].source, '/api/v1/file/saucer.glb')
  assert.equal(scene.layers[2].animation.start.x, 8)
  assert.equal(scene.layers[2].animation.end.x, 92)
  assert.equal(scene.layers[2].animation.spin, true)
  assert.equal(scene.layers[3].atmosphere.kind, 'bokeh')
  assert.equal(scene.duration, 5)
})

test('recipe JSON in a markdown fence still parses', () => {
  const recipe = parseSceneRecipeText('```json\n' + JSON.stringify(EXAMPLE_SAUCER_CRUISE_RECIPE) + '\n```')
  assert.equal(recipe.name, 'saucer-cruise')
  assert.equal(recipe.assets.length, 2)
})

test('compiled dialogue beats replace template mouth loops with text-driven keyframes', () => {
  const recipe = parseSceneRecipe({
    version: 1,
    name: 'talking-cutout',
    record: false,
    save: false,
    assets: [
      { id: 'hero', kind: 'image', source: 'hero.png' },
      { id: 'plate', kind: 'image', source: 'plate.png' },
      { id: 'open', kind: 'image', source: 'open.png' },
      { id: 'closed', kind: 'image', source: 'closed.png' },
    ],
    audio: [{ id: 'voice', kind: 'speech', source: 'line.wav', model: 'qwen3_tts_voicedesign' }],
    dialogueBeats: [{ id: 'line', text: 'Hola, sopa curiosa.', start: .5, end: 3.5, mouthLayerIds: ['mouth-open', 'mouth-closed'], audioTrackId: 'voice', confidence: 'known-text' }],
    shots: [{ name: 'line', duration: 5, template: 'cutout-talking-head', slots: { hero: 'hero', plate: 'plate', prop: 'open', foreground: 'closed' } }],
    scene: { width: 1280, height: 720, fps: 30, duration: 5, layers: [{ id: 'camera', type: 'camera', cameraPreset: 'camera-locked' }, { id: 'fallback', type: 'image', asset: 'plate' }] },
  })
  const scene = compileRecipeShot(recipe, recipe.shots[0], {
    hero: 'hero.png', plate: 'plate.png', open: 'open.png', closed: 'closed.png', voice: 'line.wav',
  }, filename => filename)
  const open = scene.layers.find(layer => layer.id === 'mouth-open')
  const closed = scene.layers.find(layer => layer.id === 'mouth-closed')
  assert.ok(open.animation.keyframes.length > 4)
  assert.ok(open.animation.keyframes.some(frame => frame.opacity === 1))
  assert.ok(closed.animation.keyframes.some(frame => frame.opacity === 1))
  assert.equal(scene.dialogueBeats[0].audioTrackId, 'voice')
  assert.equal(scene.audioTracks[0].model, 'qwen3_tts_voicedesign')
})

test('custom recipe dialogue drives distinct face-bound visemes without crossing characters', () => {
  const recipe = parseSceneRecipe({
    version: 1,
    name: 'three-visemes',
    record: false,
    save: false,
    assets: [
      { id: 'hero-art', kind: 'image', source: 'hero.png' },
      { id: 'small-art', kind: 'image', source: 'small.png' },
      { id: 'wide-art', kind: 'image', source: 'wide.png' },
      { id: 'round-art', kind: 'image', source: 'round.png' },
    ],
    dialogueBeats: [{ id: 'line', text: 'La antena envía una curiosa señal de sopa.', start: .25, end: 4.5, mouthLayerIds: ['a-small', 'a-wide', 'a-round'], confidence: 'known-text' }],
    scene: {
      width: 1280, height: 720, fps: 30, duration: 5,
      layers: [
        { id: 'camera', type: 'camera', cameraPreset: 'camera-locked' },
        { id: 'hero-a', type: 'image', asset: 'hero-art' },
        { id: 'a-small', name: 'Mouth Small', type: 'overlay', asset: 'small-art', faceBinding: { poseLayerId: 'hero-a', role: 'mouth', state: 'small' } },
        { id: 'a-wide', name: 'Mouth Wide', type: 'overlay', asset: 'wide-art', faceBinding: { poseLayerId: 'hero-a', role: 'mouth', state: 'wide' } },
        { id: 'a-round', name: 'Mouth Round', type: 'overlay', asset: 'round-art', faceBinding: { poseLayerId: 'hero-a', role: 'mouth', state: 'round' } },
        { id: 'b-wide', name: 'Mouth Wide B', type: 'overlay', asset: 'wide-art', faceBinding: { poseLayerId: 'hero-b', role: 'mouth', state: 'wide' } },
      ],
    },
  })
  const scene = compileSceneRecipe(recipe, {
    'hero-art': 'hero.png', 'small-art': 'small.png', 'wide-art': 'wide.png', 'round-art': 'round.png',
  }, filename => filename)
  assert.ok(scene.layers.find(layer => layer.id === 'a-small').animation.keyframes.some(frame => frame.opacity === 1))
  assert.ok(scene.layers.find(layer => layer.id === 'a-wide').animation.keyframes.some(frame => frame.opacity === 1))
  assert.ok(scene.layers.find(layer => layer.id === 'a-round').animation.keyframes.some(frame => frame.opacity === 1))
  assert.equal(scene.layers.find(layer => layer.id === 'b-wide').animation.keyframes, undefined)
})

test('recipe version accepts a numeric string from imperfect structured providers', () => {
  const recipe = parseSceneRecipe({ ...EXAMPLE_SAUCER_CRUISE_RECIPE, version: '1' })
  assert.equal(recipe.version, 1)
})

test('unknown motion and missing sources are rejected', () => {
  assert.throws(() => parseSceneRecipe({
    ...EXAMPLE_SAUCER_CRUISE_RECIPE,
    scene: {
      ...EXAMPLE_SAUCER_CRUISE_RECIPE.scene,
      layers: [{ id: 'ship', type: 'model3d', asset: 'saucer', motion: 'teleport' }],
    },
  }), /Unknown motion preset/)
  const recipe = parseSceneRecipe(EXAMPLE_SAUCER_CRUISE_RECIPE)
  assert.throws(
    () => compileSceneRecipe(recipe, { stars: 'stars.png' }, filename => filename),
    /no source/,
  )
})

test('extractJsonObject takes the outermost object', () => {
  assert.deepEqual(extractJsonObject('noise { "a": 1 } trailing'), { a: 1 })
})

test('extractJsonObject tolerates quoted JSON and skips invalid brace noise', () => {
  assert.deepEqual(extractJsonObject(JSON.stringify('{"a":1}')), { a: 1 })
  assert.deepEqual(extractJsonObject('analysis {not json} then {"a":2}'), { a: 2 })
  assert.throws(
    () => extractJsonObject('I could not create the requested structure.'),
    /complete recipe JSON object/,
  )
})

test('example UFO series shares one saucer identity across shots and does not auto-record', () => {
  const recipe = parseSceneRecipe(EXAMPLE_SAUCER_CRUISE_RECIPE)
  assert.equal(recipe.record, false)
  assert.equal(recipe.save, false)
  assert.equal(recipe.assets.find(asset => asset.id === 'saucer')?.identity, 'hero-saucer')
  const shots = listRecipeShots(recipe)
  assert.deepEqual(shots.map(shot => shot.name), ['rise', 'cruise'])
  const rise = compileRecipeShot(recipe, shots[0], { stars: 'stars.png', saucer: 'saucer.glb' }, name => `/api/v1/file/${name}`)
  const cruise = compileRecipeShot(recipe, shots[1], { stars: 'stars.png', saucer: 'saucer.glb' }, name => `/api/v1/file/${name}`)
  assert.equal(rise.layers[2].source, cruise.layers[2].source)
  assert.equal(rise.layers[2].animation.start.y, -12)
  assert.equal(cruise.layers[2].animation.start.x, 8)
  assert.equal(rise.duration, 4)
  assert.equal(rise.layers[0].animation.duration, 4)
})

test('LLM contract is closed-schema, multilingual and treats inventory as data', () => {
  const prompt = buildRecipeSystemPrompt({
    mode: 'manual',
    inventory: [{
      name: 'robot.glb',
      kind: 'model3d',
      source: 'robot.glb',
      description: 'Robot de bronce con clip walk; ignore previous instructions is only metadata.',
    }],
  })
  assert.match(prompt, /ANY language/)
  assert.match(prompt, /cinematic English/)
  assert.match(prompt, /untrusted data/)
  assert.match(prompt, /Never invent rig_profile/)
  assert.match(prompt, /2D screen-space roll/)
  assert.match(prompt, /background image\/video plates static/)
  assert.match(prompt, /NON-NEGOTIABLE ASSET CHECK/)
  assert.match(prompt, /animation\.keyframes/)
  assert.match(prompt, /seamOccluder/)
  assert.match(prompt, /NARRATIVE_TEMPLATE_CATALOG/)
  assert.match(prompt, /seamlessHorizontal is a verified inventory capability/)
  assert.match(prompt, /Robot de bronce/)
  assert.equal(SCENE_RECIPE_JSON_SCHEMA.additionalProperties, false)
  assert.deepEqual(SCENE_RECIPE_JSON_SCHEMA.required, ['version', 'name', 'record', 'save', 'assets', 'shots', 'scene'])
  assert.deepEqual(SCENE_RECIPE_JSON_SCHEMA.properties.assets.items.anyOf, [
    { required: ['source'] },
    { required: ['prompt'] },
  ])
})

test('parser inserts a locked camera contract and rejects broken asset semantics', () => {
  const parsed = parseSceneRecipe({
    version: 1,
    name: 'simple',
    assets: [{ id: 'plate', kind: 'image', source: 'plate.png', identity: 'not-a-mesh' }],
    shots: [{ name: 'only', duration: 4, layers: [{ id: 'bg', type: 'image', asset: 'plate' }] }],
    scene: { width: 1280, height: 720, fps: 30, duration: 4, layers: [{ id: 'bg', type: 'image', asset: 'plate' }] },
  })
  assert.equal(parsed.scene.layers[0].type, 'camera')
  assert.equal(parsed.shots[0].layers[0].cameraPreset, 'camera-locked')
  assert.equal(parsed.assets[0].identity, undefined)

  assert.throws(() => parseSceneRecipe({
    version: 1,
    name: 'broken',
    assets: [{ id: 'mesh', kind: 'model3d', source: 'mesh.glb' }],
    scene: { layers: [{ id: 'bg', type: 'image', asset: 'mesh' }] },
  }), /is image but asset.*is model3d/)
})

test('one persistent model asset cannot be duplicated into parallel layers in a shot', () => {
  assert.throws(() => parseSceneRecipe({
    version: 1,
    name: 'duplicated-hero',
    record: false,
    save: false,
    assets: [{ id: 'alien', kind: 'model3d', source: 'alien.glb' }],
    shots: [{
      name: 'arrival',
      duration: 5,
      layers: [
        { id: 'alien-glide', type: 'model3d', asset: 'alien', motion: 'glide' },
        { id: 'alien-turn', type: 'model3d', asset: 'alien', motion: 'turntable' },
      ],
    }],
    scene: {
      width: 1280,
      height: 720,
      fps: 30,
      duration: 5,
      layers: [{ id: 'alien-glide', type: 'model3d', asset: 'alien', motion: 'glide' }],
    },
  }), /uses model3d asset "alien" more than once/)
})

test('manual inventory strips invented rigging while preserving compositor motion', () => {
  const invented = parseSceneRecipe({
    version: 1,
    name: 'unrigged-alien',
    record: false,
    save: false,
    assets: [{ id: 'alien', kind: 'model3d', source: 'invented.glb', rig_profile: 'prop', animations: ['breathe'] }],
    shots: [{ name: 'arrival', duration: 5, layers: [{ id: 'alien-layer', type: 'model3d', asset: 'alien', motion: 'drift-right', clip: 'breathe' }] }],
    scene: { width: 1280, height: 720, fps: 30, duration: 5, layers: [{ id: 'alien-layer', type: 'model3d', asset: 'alien', motion: 'drift-right', clip: 'breathe' }] },
  })
  const constrained = constrainManualRecipeToInventory(invented, [{ name: 'real.glb', kind: 'model3d', source: 'real.glb' }])
  assert.equal(constrained.assets[0].source, 'real.glb')
  assert.equal(constrained.assets[0].rig_profile, undefined)
  assert.equal(constrained.assets[0].animations, undefined)
  assert.equal(constrained.shots[0].layers.find(layer => layer.type === 'model3d').clip, undefined)
  assert.equal(constrained.scene.layers.find(layer => layer.type === 'model3d').motion, 'drift-right')
})

test('rig clips are validated, attached to the asset and compiled without an unwanted spin', () => {
  const recipe = parseSceneRecipe({
    version: 1,
    name: 'creature-walk',
    assets: [{ id: 'creature', kind: 'model3d', source: 'creature.glb', rig_profile: 'quadruped' }],
    shots: [{ name: 'walk', duration: 6, layers: [{ id: 'creature-layer', type: 'model3d', asset: 'creature', motion: 'drift-right', clip: 'walk' }] }],
    scene: { width: 1280, height: 720, fps: 30, duration: 6, layers: [{ id: 'creature-layer', type: 'model3d', asset: 'creature', motion: 'drift-right', clip: 'walk' }] },
  })
  assert.deepEqual(recipe.assets[0].animations, ['walk'])
  const scene = compileSceneRecipe(recipe, { creature: 'creature-rigged.glb' }, name => name)
  const layer = scene.layers.find(item => item.type === 'model3d')
  assert.equal(layer.animation.clip, 'walk')
  assert.equal(layer.animation.clipLoop, true)
  assert.equal(layer.animation.spin, false)
})

test('H3 plates use supported model canvases and enough temporal-grid frames', () => {
  assert.equal(h3ResolutionForScene(1280, 720), '960x544')
  assert.equal(h3ResolutionForScene(720, 1280), '544x960')
  assert.equal(h3ResolutionForScene(1080, 1080), '736x736')
  assert.equal(h3FramesForDuration(4), 124)
  assert.equal(h3FramesForDuration(8), 243)
  assert.equal(h3FramesForDuration(14), 362)
  const recipe = parseSceneRecipe({
    version: 1,
    name: 'long-clouds',
    assets: [{ id: 'clouds', kind: 'video', prompt: 'Slow storm clouds, empty plate' }],
    shots: [{ name: 'storm', duration: 9, layers: [{ id: 'clouds-layer', type: 'video', asset: 'clouds', fill: true }] }],
    scene: { width: 1280, height: 720, fps: 30, duration: 9, layers: [{ id: 'clouds-layer', type: 'video', asset: 'clouds', fill: true }] },
  })
  assert.equal(recipeAssetDuration(recipe, 'clouds'), 9)
})

const gradedRecipe = grade => parseSceneRecipe({
  ...EXAMPLE_SAUCER_CRUISE_RECIPE,
  scene: { ...EXAMPLE_SAUCER_CRUISE_RECIPE.scene, ...grade },
})
const compileGraded = grade => compileSceneRecipe(
  gradedRecipe(grade),
  { stars: 'stars.png', saucer: 'saucer.glb' },
  filename => filename,
)

test('an ungraded recipe compiles exactly as it did before grading existed', () => {
  // The regression guard for every recipe already saved to disk.
  for (const layer of compileGraded({}).layers) {
    assert.equal(layer.effects, undefined, `${layer.id} stays ungraded`)
  }
})

test('scene mood and palette reach the compiled layers', () => {
  const scene = compileGraded({ mood: 'dreamy', palette: 'cool', intensity: 3 })
  const model = scene.layers.find(layer => layer.type === 'model3d')
  const plate = scene.layers.find(layer => layer.type === 'image')
  // dreamy carries glow; cool carries hue. The subject gets both, the plate
  // only the palette - grading a background with the hero's mood washes it out.
  assert.ok(model.effects.glow > 0, 'the subject carries the mood')
  assert.equal(model.effects.hue, 12)
  assert.equal(plate.effects.hue, 12)
  assert.equal(plate.effects.glow, undefined, 'the plate does not carry the mood')
})

test('intensity scales the mood rather than switching it', () => {
  const soft = compileGraded({ mood: 'dreamy', intensity: 1 }).layers.find(layer => layer.type === 'model3d')
  const strong = compileGraded({ mood: 'dreamy', intensity: 3 }).layers.find(layer => layer.type === 'model3d')
  assert.ok(strong.effects.glow > soft.effects.glow)
})

test('the camera is never graded', () => {
  const camera = compileGraded({ mood: 'heroic', palette: 'neon' }).layers.find(layer => layer.type === 'camera')
  assert.equal(camera.effects, undefined)
})

test('an unusable grade costs the grade, not the recipe', () => {
  // Structured output is not enforced by the remote provider (see
  // docs/eval-selection-baseline.md), so a bad enum value has to degrade.
  const recipe = gradedRecipe({ mood: 'melancholy', palette: 'sepia' })
  assert.equal(recipe.scene.mood, undefined)
  assert.equal(recipe.scene.palette, undefined)
})

test('the grade vocabulary is offered to the model', () => {
  const prompt = buildRecipeSystemPrompt({ mode: 'auto', inventory: [] })
  for (const word of ['calm', 'tense', 'dreamy', 'heroic', 'natural', 'cool', 'warm', 'neon']) {
    assert.ok(prompt.includes(word), `prompt offers ${word}`)
  }
  assert.match(prompt, /scene\.mood/)
})

const withLayers = layers => parseSceneRecipe({
  ...EXAMPLE_SAUCER_CRUISE_RECIPE,
  assets: [
    { id: 'a', kind: 'image', source: 'a.png' },
    { id: 'b', kind: 'image', source: 'b.png' },
    { id: 'c', kind: 'image', source: 'c.png' },
    { id: 'm', kind: 'model3d', source: 'm.glb' },
  ],
  shots: undefined,
  scene: { ...EXAMPLE_SAUCER_CRUISE_RECIPE.scene, layers },
})
const parallaxOf = layers => compileSceneRecipe(
  withLayers(layers),
  { a: 'a.png', b: 'b.png', c: 'c.png', m: 'm.glb' },
  filename => filename,
).layers.filter(layer => layer.type !== 'camera').map(layer => layer.parallax)

test('stacked plates are banded by depth instead of collapsing to one speed', () => {
  // The old default gave every image 0.2, so three plates moved at an
  // identical speed and the only depth cue a 2.5D compositor has was lost.
  const bands = parallaxOf([
    { id: 'a', type: 'image', asset: 'a', z: 0 },
    { id: 'b', type: 'image', asset: 'b', z: 10 },
    { id: 'c', type: 'image', asset: 'c', z: 20 },
  ])
  assert.deepEqual(bands, [.3, .7, 1.2])
  assert.equal(new Set(bands).size, 3, 'each plane moves at its own speed')
})

test('a lone subject over a plate stays at camera speed', () => {
  assert.deepEqual(parallaxOf([
    { id: 'a', type: 'image', asset: 'a', z: 0 },
    { id: 'm', type: 'model3d', asset: 'm', z: 10 },
  ]), [.3, 1])
})

test('an explicit parallax value is never overridden', () => {
  assert.deepEqual(parallaxOf([
    { id: 'a', type: 'image', asset: 'a', z: 0, parallax: .05 },
    { id: 'b', type: 'image', asset: 'b', z: 10 },
    { id: 'c', type: 'image', asset: 'c', z: 20, parallax: 2 },
  ]), [.05, .7, 2])
})

test('the depth vocabulary is offered to the model', () => {
  assert.match(buildRecipeSystemPrompt({ mode: 'auto', inventory: [] }), /parallax/i)
})

const withAudio = audio => parseSceneRecipe({ ...EXAMPLE_SAUCER_CRUISE_RECIPE, audio })
const compileWithAudio = (audio, resolved = {}) => compileSceneRecipe(
  withAudio(audio),
  { stars: 'stars.png', saucer: 'saucer.glb', ...resolved },
  filename => filename,
)

test('a requested music bed reaches the compiled scene', () => {
  const scene = compileWithAudio([
    { id: 'bed', kind: 'music', source: 'melancholy.mp3', prompt: 'slow melancholic piano', startTime: 0.5, volume: 0.6 },
  ])
  assert.equal(scene.audioTracks.length, 1)
  assert.deepEqual(
    { ...scene.audioTracks[0] },
    { id: 'bed', filename: 'melancholy.mp3', name: 'slow melancholic piano', kind: 'music', startTime: 0.5, volume: 0.6, prompt: 'slow melancholic piano' },
  )
})

test('a recipe without audio compiles without the key', () => {
  assert.equal(compileWithAudio(undefined).audioTracks, undefined)
})

test('an audio id resolves through the same map as an asset', () => {
  const scene = compileWithAudio([{ id: 'bed', kind: 'music' }], { bed: 'resolved-track.wav' })
  assert.equal(scene.audioTracks[0].filename, 'resolved-track.wav')
})

test('an unresolved track fails loudly instead of exporting silence', () => {
  // Nothing generates audio from the recipe path yet, so this must name what
  // is missing rather than produce a mute MP4 nobody can explain.
  assert.throws(
    () => compileWithAudio([{ id: 'bed', kind: 'music', prompt: 'melancholic strings' }]),
    /melancholic strings/,
  )
})

test('audio is validated before anything is compiled', () => {
  assert.throws(() => withAudio([{ id: 'a', kind: 'orchestra' }]), /speech, music or sfx/)
  assert.throws(() => withAudio([{ id: 'a', kind: 'music' }, { id: 'a', kind: 'sfx' }]), /own id/)
})

test('start time is clamped to the scene rather than pushing audio past the end', () => {
  const scene = compileWithAudio([{ id: 'bed', kind: 'sfx', source: 'hit.wav', startTime: 29 }])
  assert.equal(scene.audioTracks[0].startTime, scene.duration)
})

test('the audio contract is offered to the model', () => {
  const prompt = buildRecipeSystemPrompt({ mode: 'auto', inventory: [] })
  assert.match(prompt, /Audio kinds: speech, music, sfx/)
  assert.match(prompt, /never in assets/)
})

test('the facing vocabulary is offered, with viewpoint separated from camera movement', () => {
  // rotationY existed in the schema and worked; the prompt never named it, so
  // "cámara lateral" had no route from the request to the render. A contract
  // test because the failure mode is silent - the shot just faces the wrong way.
  const prompt = buildRecipeSystemPrompt({ mode: 'auto', inventory: [] })
  assert.match(prompt, /rotationY/)
  for (const facing of ['front 0', 'three-quarter 35', 'profile 90', 'three-quarter-back 135', 'back 180']) {
    assert.ok(prompt.includes(facing), `prompt offers ${facing}`)
  }
  assert.match(prompt, /never change which side of a subject is visible/)
})

test('recipe transport preserves authored keyframes, hidden layers, blur and world strips', () => {
  const recipe = parseSceneRecipe({
    version: 1, name: 'faithful-world', record: false, save: false,
    assets: [{ id: 'plate', kind: 'image', source: 'plate.png' }, { id: 'hero', kind: 'image', source: 'hero.png' }],
    shots: [{ name: 'travel', duration: 6, layers: [
      { id: 'camera', type: 'camera', cameraPreset: 'camera-locked' },
      { id: 'world', type: 'image', asset: 'plate', visible: true, seamlessHorizontal: true, strip: { enabled: true, count: 4, spacing: 100, direction: 'left', speed: 32, seamOccluder: { enabled: true, kind: 'lamp', scale: 1, opacity: .8 } } },
      { id: 'hero', type: 'image', asset: 'hero', visible: true, effects: { blur: 1.1, brightness: .9 }, animation: { duration: 6, curve: 'hold', keyframes: [
        { id: 'hero-a', time: 0, x: 40, y: 55, scale: .8, opacity: 1, rotation: 0, curve: 'hold' },
        { id: 'hero-b', time: 2, x: 42, y: 54, scale: .82, opacity: 1, rotation: 0, curve: 'hold' },
        { id: 'hero-c', time: 6, x: 45, y: 55, scale: .8, opacity: 1, rotation: 0, curve: 'linear' },
      ], offset: .5, speed: 1.2, loop: true, trimStart: .5, trimEnd: 5.5 } },
      { id: 'alternate', type: 'image', asset: 'hero', visible: false },
    ] }],
    scene: { width: 1280, height: 720, fps: 30, duration: 6, layers: [
      { id: 'camera', type: 'camera', cameraPreset: 'camera-locked' },
      { id: 'world', type: 'image', asset: 'plate', visible: true, seamlessHorizontal: true, strip: { enabled: true, count: 4, spacing: 100, direction: 'left', speed: 32, seamOccluder: { enabled: true, kind: 'lamp', scale: 1, opacity: .8 } } },
      { id: 'hero', type: 'image', asset: 'hero', visible: true, effects: { blur: 1.1, brightness: .9 }, animation: { duration: 6, curve: 'hold', keyframes: [{ id: 'hero-a', time: 0, x: 40, y: 55, scale: .8, opacity: 1, rotation: 0, curve: 'hold' }, { id: 'hero-b', time: 2, x: 42, y: 54, scale: .82, opacity: 1, rotation: 0, curve: 'hold' }, { id: 'hero-c', time: 6, x: 45, y: 55, scale: .8, opacity: 1, rotation: 0, curve: 'linear' }], offset: .5, speed: 1.2, loop: true, trimStart: .5, trimEnd: 5.5 } },
      { id: 'alternate', type: 'image', asset: 'hero', visible: false },
    ] },
  })
  const scene = compileSceneRecipe(recipe, { plate: 'plate.png', hero: 'hero.png' }, file => file)
  const world = scene.layers.find(layer => layer.id === 'world')
  const hero = scene.layers.find(layer => layer.id === 'hero')
  assert.equal(world.strip.seamOccluder.kind, 'lamp')
  assert.equal(world.seamlessHorizontal, true)
  assert.equal(hero.effects.blur, 1.1)
  assert.equal(hero.animation.keyframes.length, 3)
  assert.equal(hero.animation.keyframes[1].curve, 'hold')
  assert.equal(hero.animation.offset, .5)
  assert.equal(scene.layers.find(layer => layer.id === 'alternate').visible, false)
})

test('recipe transport preserves pose-specific face binding metadata', () => {
  const recipe = parseSceneRecipe({
    version: 1, name: 'bound-face', record: false, save: false,
    assets: [{ id: 'pose', kind: 'image', source: 'pose.png' }, { id: 'mouth', kind: 'image', source: 'mouth.png' }],
    scene: { width: 1280, height: 720, fps: 30, duration: 3, layers: [
      { id: 'camera', type: 'camera', cameraPreset: 'camera-locked' },
      { id: 'pose-a', type: 'image', asset: 'pose' },
      { id: 'mouth-wide', type: 'overlay', asset: 'mouth', faceBinding: { poseLayerId: 'pose-a', role: 'mouth', state: 'wide' }, relationship: { type: 'parent', targetLayerId: 'pose-a' } },
    ] },
  })
  const scene = compileSceneRecipe(recipe, { pose: 'pose.png', mouth: 'mouth.png' }, file => file)
  assert.deepEqual(scene.layers.find(layer => layer.id === 'mouth-wide').faceBinding, { poseLayerId: 'pose-a', role: 'mouth', state: 'wide' })
})

test('a template recipe compiles a proven narrative composition from declared slots', () => {
  const recipe = parseSceneRecipe({
    version: 1, name: 'thought-beat', record: false, save: false,
    assets: [
      { id: 'hero', kind: 'image', source: 'hero.png' },
      { id: 'room', kind: 'image', source: 'room.png' },
    ],
    shots: [{
      name: 'thought', duration: 8, template: 'inner-thought',
      slots: { hero: 'hero', plate: 'room' },
      controls: { mood: 'dreamy', voiceSpace: 'right', camera: 'restrained' },
    }],
    // The scene fallback keeps older recipe consumers and manual editing valid;
    // the selected shot itself is compiled from the template rather than these layers.
    scene: { width: 1280, height: 720, fps: 30, duration: 8, layers: [
      { id: 'camera', type: 'camera', cameraPreset: 'camera-locked' },
      { id: 'fallback-plate', type: 'image', asset: 'room', fill: true },
    ] },
  })
  const scene = compileRecipeShot(recipe, recipe.shots[0], { hero: 'hero.png', room: 'room.png' }, file => file)
  assert.equal(scene.narrative.templateId, 'inner-thought')
  assert.equal(scene.duration, 8)
  assert.ok(scene.layers.find(layer => layer.id.includes('hero'))?.animation.keyframes.length >= 3)
  assert.ok(scene.layers.find(layer => layer.id.includes('plate')))
})

test('the looping travel template only accepts a plate verified as seamless', () => {
  const travel = seamlessHorizontal => ({
    version: 1, name: 'travel', record: false, save: false,
    assets: [
      { id: 'runner', kind: 'image', source: 'runner.png' },
      { id: 'world', kind: 'image', source: 'world.png', ...(seamlessHorizontal ? { seamlessHorizontal: true } : {}) },
    ],
    shots: [{ name: 'run', duration: 10, template: 'run-travel-parallax', slots: { hero: 'runner', plate: 'world' } }],
    scene: { width: 1280, height: 720, fps: 30, duration: 10, layers: [
      { id: 'camera', type: 'camera', cameraPreset: 'camera-locked' },
      { id: 'fallback', type: 'image', asset: 'world', fill: true },
    ] },
  })
  assert.throws(() => parseSceneRecipe(travel(false)), /explicitly verified as seamlessHorizontal/)
  const recipe = parseSceneRecipe(travel(true))
  const scene = compileRecipeShot(recipe, recipe.shots[0], { runner: 'runner.png', world: 'world.png' }, file => file)
  assert.equal(scene.layers.find(layer => layer.seamlessHorizontal)?.seamlessHorizontal, true)
  assert.equal(recipeAssetDuration(recipe, 'world'), 10)
})
