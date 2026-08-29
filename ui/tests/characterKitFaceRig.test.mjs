import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import { applyFaceRigMouthPreset, assessFaceRigPlacement, characterKitPosePrompt, classifyCharacterKitAlpha, composeCharacterKitLook, containedImageRect, faceRigAnchorFor, faceRigAnchorFromRegion, faceRigGenerationRequests, faceRigOverlayPreviewStyle, faceRigPrompt, faceRigRegionFromAnchor, faceRigVisemeAt, lockFaceRigMouthPlacement, previewFaceRigDialogue, previewFaceRigDialogueFromAudio, previewPercentToImagePixel, registerCleanedFaceRigAsset, registerGeneratedFaceRigAsset, setFaceRigAnchor, setFaceRigReviewState, validateFaceRigPose, wipeMouthRegion } from '../src/lib/characterKitFaceRig.ts'
import { registerWipedKitPose } from '../src/lib/characterKit.ts'

const pose = { id: 'base', name: 'Base', source: 'base.png', kind: 'image', alphaStatus: 'opaque', reviewState: 'approved' }
const generated = state => ({ id: `generated-${state}`, name: state, source: `${state}.png`, kind: 'overlay', alphaStatus: 'transparent', reviewState: 'approved' })

test('alpha classification detects a materially transparent RGBA image', () => {
  const rgba = new Uint8ClampedArray([255, 255, 255, 0, 255, 255, 255, 255, 255, 255, 255, 128, 255, 255, 255, 255])
  assert.deepEqual(classifyCharacterKitAlpha(rgba), { pixelCount: 4, transparentRatio: .5, translucentRatio: .25, opaqueRatio: .5, status: 'transparent' })
})

test('alpha classification accepts an effectively opaque image', () => {
  const rgba = new Uint8ClampedArray([0, 0, 0, 255, 1, 1, 1, 255, 2, 2, 2, 254, 3, 3, 3, 255])
  const metrics = classifyCharacterKitAlpha(rgba)
  assert.equal(metrics.pixelCount, 4)
  assert.equal(metrics.opaqueRatio, .75)
  assert.equal(metrics.status, 'unknown')
  assert.equal(classifyCharacterKitAlpha(new Uint8ClampedArray([0, 0, 0, 255, 1, 1, 1, 255, 2, 2, 2, 255, 3, 3, 3, 255])).status, 'opaque')
})

test('alpha classification returns unknown for invalid pixel data', () => {
  assert.equal(classifyCharacterKitAlpha(new Uint8ClampedArray()).status, 'unknown')
  assert.equal(classifyCharacterKitAlpha(new Uint8ClampedArray([0, 0, 0])).status, 'unknown')
  assert.equal(classifyCharacterKitAlpha(/** @type {any} */ (new Uint8Array([0, 0, 0, 255]))).status, 'unknown')
})

test('Face Rig validates a persistent approved base or pose', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  assert.equal(validateFaceRigPose(kit).pose.source, 'base.png')
  assert.throws(() => validateFaceRigPose({ ...kit, base: { ...pose, reviewState: 'pending' } }), /Review and approve/)
  assert.throws(() => validateFaceRigPose({ ...kit, base: { ...pose, source: 'blob:temporary' } }), /persistent pose source/)
})

test('Face Rig produces six identity-preserving generation requests including open eyes', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const requests = faceRigGenerationRequests(kit, 'base', 'a shy schoolgirl with red braids')
  assert.deepEqual(requests.map(request => request.state), ['closed', 'small', 'wide', 'round', 'open-eyes', 'blink'])
  assert.ok(requests.every(request => request.reference === 'base.png' && request.prompt.includes('a shy schoolgirl with red braids')))
  assert.ok(requests.every(request => request.prompt.includes('ONLY') && request.prompt.includes('transparent') && request.prompt.includes('no full character')))
  assert.match(faceRigPrompt(kit, 'blink'), /eyelids fully closed/)
  assert.match(faceRigPrompt(kit, 'open-eyes'), /eyes open/)
  assert.match(faceRigPrompt(kit, 'wide'), /mouth overlay sprite/)
})

test('registering and reviewing a generated state is immutable and records provenance', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const next = registerGeneratedFaceRigAsset(kit, 'wide', generated('wide'), { poseId: 'base', reference: 'base.png', prompt: 'wide prompt' })
  assert.equal(kit.mouth.wide, undefined)
  assert.equal(next.mouth.wide.reviewState, 'pending')
  assert.equal(next.provenance[0].method, 'character-kit-face-rig')
  const approved = setFaceRigReviewState(next, 'wide', 'approved')
  assert.equal(next.mouth.wide.reviewState, 'pending')
  assert.equal(approved.mouth.wide.reviewState, 'approved')
})

test('blink is registered in eyes and rejects transient generated sources', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const next = registerGeneratedFaceRigAsset(kit, 'blink', generated('blink'), { poseId: 'base', reference: 'base.png', prompt: 'blink prompt' })
  assert.equal(next.eyes.blink.reviewState, 'pending')
  const open = registerGeneratedFaceRigAsset(kit, 'open-eyes', generated('open-eyes'), { poseId: 'base', reference: 'base.png', prompt: 'open eyes' })
  assert.equal(open.eyes.open.reviewState, 'pending')
  assert.throws(() => registerGeneratedFaceRigAsset(kit, 'round', { ...generated('round'), source: 'blob:temp' }, { poseId: 'base', reference: 'base.png', prompt: 'round' }), /persistent source/)
})

test('cleaning a Face Rig overlay keeps it pending and records provenance', () => {
  const kit = registerGeneratedFaceRigAsset({ ...createCharacterKit('Luna'), base: pose }, 'wide', generated('wide'), { poseId: 'base', reference: 'base.png', prompt: 'wide prompt' })
  const cleaned = registerCleanedFaceRigAsset(kit, 'wide', {
    source: '/api/v1/file/wide.cleanup-abcd.png',
    filename: 'wide.cleanup-abcd.png',
    original: 'wide.png',
    width: 48,
    height: 24,
    alpha: { pixelCount: 4, transparentRatio: .5, translucentRatio: .25, opaqueRatio: .5, status: 'transparent' },
    method: 'rembg-u2net',
    padding: 8,
    model: 'u2net',
  })
  assert.equal(kit.mouth.wide.source, 'wide.png')
  assert.equal(cleaned.mouth.wide.source, '/api/v1/file/wide.cleanup-abcd.png')
  assert.equal(cleaned.mouth.wide.reviewState, 'pending')
  assert.equal(cleaned.mouth.wide.alphaStatus, 'transparent')
  assert.equal(cleaned.provenance.at(-1).method, 'character-kit-face-rig-cleanup')
  assert.throws(() => registerCleanedFaceRigAsset(kit, 'closed', {
    source: '/api/v1/file/closed.cleanup.png', filename: 'closed.cleanup.png', original: 'closed.png',
    width: 8, height: 8, alpha: { pixelCount: 1, transparentRatio: 1, translucentRatio: 0, opaqueRatio: 0, status: 'transparent' },
    method: 'rembg-u2net', padding: 8,
  }), /no generated closed asset/)
})

test('Face Rig anchors fall back to the legacy mouth slot and save per-state placement', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose, anchors: { base: { mouth: { offsetX: 0, offsetY: -19, scale: .041, rotation: 0 } } } }
  assert.deepEqual(faceRigAnchorFor(kit, 'base', 'wide'), { offsetX: 0, offsetY: -19, scale: .041, rotation: 0 })
  const next = setFaceRigAnchor(kit, 'base', 'wide', { offsetX: 1, offsetY: -18, scale: .055, rotation: 2 })
  assert.equal(kit.anchors.base.mouthStates, undefined)
  assert.deepEqual(next.anchors.base.mouthStates.wide, { offsetX: 1, offsetY: -18, scale: .055, rotation: 2 })
  assert.deepEqual(next.anchors.base.mouth, { offsetX: 0, offsetY: -19, scale: .041, rotation: 0 })
  const blinked = setFaceRigAnchor(next, 'base', 'blink', { offsetX: 0, offsetY: -30.5, scale: .149, rotation: 0 })
  assert.deepEqual(blinked.anchors.base.eyes, { offsetX: 0, offsetY: -30.5, scale: .149, rotation: 0 })
  assert.equal(blinked.provenance.at(-1).method, 'character-kit-face-rig-anchor')
})

test('placement preview uses relative CSS and warns when the overlay misses the face', () => {
  const style = faceRigOverlayPreviewStyle({ offsetX: 0, offsetY: -19, scale: .041, rotation: 0 })
  assert.equal(style.left, '50%')
  assert.equal(style.top, '31%')
  assert.equal(style.width, '4.1%')
  assert.equal(assessFaceRigPlacement({ offsetX: 0, offsetY: -19, scale: .041, rotation: 0 }, 'wide').ok, true)
  const huge = assessFaceRigPlacement({ offsetX: 80, offsetY: 8, scale: .9, rotation: 0 }, 'wide')
  assert.equal(huge.ok, false)
  assert.ok(huge.warnings.some(warning => /miss the face/.test(warning)))
  assert.ok(huge.warnings.some(warning => /larger than a typical viseme/.test(warning)))
})

test('dialogue preview marks missing mouths as fallbacks and stays off the kit', () => {
  const kit = {
    ...createCharacterKit('Luna'),
    base: pose,
    mouth: { closed: generated('closed'), wide: generated('wide') },
  }
  const preview = previewFaceRigDialogue(kit, 'The square is frozen and the bell is too loud.', 3)
  assert.equal(preview.end, 3)
  assert.deepEqual(preview.available, ['closed', 'wide'])
  assert.deepEqual(preview.missing, ['small', 'round'])
  assert.ok(preview.visemes.some(beat => beat.state === 'closed'))
  assert.ok(preview.visemes.filter(beat => beat.fallback).every(beat => beat.sourceState === 'wide' || beat.sourceState === 'closed'))
  assert.equal(kit.mouth.small, undefined)
  assert.equal(faceRigVisemeAt(preview, 0)?.state, preview.visemes[0].state)
})

test('applying a mouth style pack stays pending and does not invent blink', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const next = applyFaceRigMouthPreset(kit, {
    id: 'paper-cut',
    label: 'Paper cut',
    states: {
      closed: { file: 'paper-cut/closed.png' },
      small: { file: 'paper-cut/small.png' },
      wide: { file: 'paper-cut/wide.png' },
      round: { file: 'paper-cut/round.png' },
    },
  })
  assert.equal(kit.mouth.wide, undefined)
  assert.equal(next.mouth.closed.reviewState, 'pending')
  assert.equal(next.mouth.wide.source, '/character-kit-presets/mouths/paper-cut/wide.png')
  assert.equal(next.eyes.blink, undefined)
  assert.equal(next.provenance.at(-1).packId, 'paper-cut')
})

test('look chips compose a style-only prompt and fill overlay + body requests', () => {
  const look = composeCharacterKitLook({
    name: 'Luma',
    traits: 'afro hair, beanie',
    stylePrompt: 'hand-sculpted plasticine clay, visible fingerprints, matte clay material, stop-motion puppet',
  })
  const kit = { ...createCharacterKit('Luma'), base: pose, lookNotes: look }
  assert.match(look, /afro hair/)
  assert.match(characterKitPosePrompt(kit), /plasticine/)
  assert.match(characterKitPosePrompt(kit), /full-body standing character cutout/)
  assert.match(faceRigPrompt(kit, 'wide'), /mouth overlay sprite only/)
  assert.match(faceRigPrompt(kit, 'blink'), /eyelids fully closed/)
  const requests = faceRigGenerationRequests(kit)
  assert.ok(requests.every(request => request.prompt.includes('afro hair') && request.prompt.includes('plasticine')))
})

test('mouth region round-trips through the Face Rig anchor and maps onto the pose pixels', () => {
  const anchor = { offsetX: 2, offsetY: -16, scale: .07, rotation: 0 }
  const region = faceRigRegionFromAnchor(anchor)
  const back = faceRigAnchorFromRegion(region)
  assert.equal(Number(back.offsetX.toFixed(4)), 2)
  assert.equal(Number(back.offsetY.toFixed(4)), -16)
  assert.equal(Number(back.scale.toFixed(4)), .07)
  assert.deepEqual(containedImageRect(100, 100, 100, 100), { x: 0, y: 0, width: 100, height: 100 })
  const pixel = previewPercentToImagePixel(50, 32, 200, 300)
  assert.ok(pixel.x > 90 && pixel.x < 110)
  assert.ok(pixel.y > 80 && pixel.y < 120)
})

test('wiping a mouth region fills the ellipse without touching distant pixels', () => {
  const width = 8
  const height = 8
  const rgba = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4
      const mouth = x >= 3 && x <= 4 && y >= 3 && y <= 4
      rgba[i] = mouth ? 40 : 200
      rgba[i + 1] = mouth ? 10 : 160
      rgba[i + 2] = mouth ? 10 : 130
      rgba[i + 3] = 255
    }
  }
  const wiped = wipeMouthRegion(rgba, width, height, { cx: 3.5, cy: 3.5, rx: 1.6, ry: 1.6 })
  const center = (3 * width + 3) * 4
  assert.ok(wiped[center] > 120)
  assert.equal(wiped[0], 200)
  assert.equal(rgba[center], 40)
  const kit = registerWipedKitPose(
    { ...createCharacterKit('Luna'), base: pose },
    'base',
    { ...pose, source: '/api/v1/file/luna-wiped.png', name: 'Wiped' },
  )
  assert.equal(kit.base.source, '/api/v1/file/luna-wiped.png')
  assert.equal(kit.base.reviewState, 'approved')
  assert.equal(kit.provenance.at(-1).method, 'character-kit-mouth-wipe')
})

test('locking mouth placement copies one calibration onto every viseme', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose }
  const locked = lockFaceRigMouthPlacement(kit, 'base', { offsetX: 1, offsetY: -14, scale: .05, rotation: 0 })
  assert.equal(kit.anchors.base, undefined)
  assert.deepEqual(locked.anchors.base.mouth, { offsetX: 1, offsetY: -14, scale: .05, rotation: 0 })
  assert.deepEqual(locked.anchors.base.mouthStates.closed, locked.anchors.base.mouth)
  assert.deepEqual(locked.anchors.base.mouthStates.wide, locked.anchors.base.mouth)
  assert.equal(faceRigAnchorFor(locked, 'base', 'blink').scale, .12)
  assert.equal(locked.provenance.at(-1).method, 'character-kit-face-rig-lock-mouths')
})

test('audio-aligned dialogue preview stays within four seconds', () => {
  const kit = { ...createCharacterKit('Luna'), base: pose, mouth: { closed: generated('closed'), wide: generated('wide'), round: generated('round') } }
  const preview = previewFaceRigDialogueFromAudio(kit, 'Hello there', [
    { text: 'Hello', start: 0.1, end: 0.8 },
    { text: 'there', start: 0.9, end: 5.2 },
  ])
  assert.ok(preview.end <= 4)
  assert.ok(preview.visemes.length > 1)
})
