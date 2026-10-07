import assert from 'node:assert/strict'
import test from 'node:test'
import { characterKitMouthSource, createCharacterKit, mountCharacterKitLayers, type CharacterKit, type CharacterKitAsset } from '../src/lib/characterKit'
import { lockFaceRigEyePlacement, lockFaceRigMouthPlacement } from '../src/lib/characterKitFaceRig'
import { flatRigPoseSource, imageToZoom, mouthLineRigRequest, mouthZoom, savedMouthLine, zoomToImage } from '../src/lib/flatRigMouth'
import { compileSeriesShot, type ShotSpec } from '../scripts/seriesShot.ts'

const STATES = ['closed', 'small', 'wide', 'round', 'pressed', 'medium', 'pucker', 'bite', 'tongue'] as const
const file = (name: string) => `/api/v1/file/${name}.png?workspace=cast`
const asset = (id: string, kind: 'image' | 'overlay' = 'overlay', size?: { width: number; height: number }): CharacterKitAsset => ({
  id, name: id, source: file(id), kind, alphaStatus: 'transparent', reviewState: 'approved', ...size })
const anchor = (offsetY: number) => ({ offsetX: 2, offsetY, scale: 0.12, rotation: 0 })
const own = (pose: string) => Object.fromEntries(STATES.map(state => [state, file(`kit-hero-${pose}-mouth-${state}`)]))

/** A kit the flat rig made with warp mouths: each pose has its own, the kit's are the base pose's. */
function warpKit(): CharacterKit {
  const kit = createCharacterKit('Hero')
  kit.id = 'hero'
  kit.base = asset('kit-hero-base-rig-1', 'image', { width: 800, height: 1000 })
  kit.poses = { busto: asset('kit-hero-busto-rig-1', 'image', { width: 900, height: 1100 }), added: asset('hero-added', 'image', { width: 800, height: 1000 }) }
  kit.mouth = Object.fromEntries(STATES.map(state => [state, { ...asset(`hero-mouth-${state}`), source: file(`kit-hero-base-mouth-${state}`) }]))
  kit.mouthMapping = { rest: 'closed', M: 'pressed', A: 'wide', E: 'medium', I: 'small', O: 'round', U: 'pucker', F: 'bite', L: 'tongue' }
  kit.eyes = { blink: asset('hero-blink') }
  kit.anchors = {
    base: { mouth: anchor(-20), eyes: anchor(-30), mouthSources: own('base') },
    busto: { mouth: anchor(-10), eyes: anchor(-25), mouthSources: own('busto'), blinkSource: file('hero-busto-blink') },
    added: { mouth: anchor(-18), eyes: anchor(-28) },
  }
  kit.provenance = [{ method: 'flat-rig', sources: { base: file('hero-key'), busto: file('hero-busto-key') }, style: { mouthStyle: 'warp', smile: 0.15 },
    hints: { busto: { eyes: [40, 20], mouth: [41, 33] } }, mouthLines: { base: { mouth: [44.4, 17.4], mouthWidth: 5, found: true, from: 'landmarks' } } }]
  return kit
}

const mouths = (layers: ReturnType<typeof mountCharacterKitLayers>) =>
  Object.fromEntries(layers.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => [layer.faceBinding!.state, layer.source]))

test('each pose of a warp kit is mounted with its own mouths, and a pose without any with none', () => {
  const kit = warpKit()
  assert.deepEqual(mouths(mountCharacterKitLayers(kit, 'busto')), own('busto'))
  assert.deepEqual(mouths(mountCharacterKitLayers(kit, 'base')), own('base'))
  assert.deepEqual(mouths(mountCharacterKitLayers(kit, 'added')), {}, 'never the base pose\'s face on another pose')
  // The mouths still share the kit's review: a pending kit mouth is not mounted on any pose.
  kit.mouth.wide = { ...kit.mouth.wide!, reviewState: 'pending' }
  assert.equal(mouths(mountCharacterKitLayers(kit, 'busto')).wide, undefined)
})

test('a drawing put on the kit later is every pose\'s again', () => {
  const kit = warpKit()
  kit.mouth.wide = asset('pack-wide')
  assert.equal(characterKitMouthSource(kit, 'busto', 'wide'), file('pack-wide'))
  assert.equal(characterKitMouthSource(kit, 'added', 'wide'), file('pack-wide'))
  assert.equal(characterKitMouthSource(kit, 'busto', 'closed'), own('busto').closed)
})

test('a Series shot compiles a warp pose with its own mouths at its own anchor', () => {
  const kit = warpKit()
  const spec: ShotSpec = { name: 'Pilot · s01', workspace: 'cast', width: 1920, height: 1080, fps: 24, duration: 2, framing: 'close',
    background: { source: file('room'), kind: 'image' }, cast: [{ kitId: 'hero', poseId: 'busto', x: 50 }],
    lines: [{ id: 'l1', kitId: 'hero', text: 'Hola.', start: 0.2, end: 1.2, filename: 'l1.wav' }] }
  const scene = compileSeriesShot({ hero: kit }, spec)
  const sources = scene.layers.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => layer.source)
  assert.deepEqual(new Set(sources), new Set(Object.values(own('busto'))))
})

test('moving a warp pose\'s mouth keeps its own drawings and blink; another pose never inherits the base\'s', () => {
  const kit = warpKit()
  const moved = lockFaceRigMouthPlacement(kit, 'busto', anchor(-9))
  assert.deepEqual(moved.anchors.busto.mouthSources, own('busto'))
  assert.equal(moved.anchors.busto.blinkSource, file('hero-busto-blink'))
  const fresh = { ...kit, anchors: { base: kit.anchors.base } }
  assert.equal(lockFaceRigEyePlacement(fresh, 'other', anchor(-30)).anchors.other.mouthSources, undefined)
  assert.equal(lockFaceRigMouthPlacement(fresh, 'other', anchor(-30)).anchors.other.mouthSources, undefined)
})

test('the mouth line editor reads the rigged original, the saved line and re-rigs with the hint', () => {
  const kit = warpKit()
  assert.equal(flatRigPoseSource(kit, 'busto'), file('hero-busto-key'), 'the original, not the rig output')
  assert.equal(flatRigPoseSource(kit, 'added'), file('hero-added'))
  assert.deepEqual(savedMouthLine(kit, 'base'), { mouth: [44.4, 17.4], mouthWidth: 5 })
  assert.equal(savedMouthLine(kit, 'busto'), undefined, 'a hint point without a width is no line yet')
  const request = mouthLineRigRequest(kit, 'busto', { mouth: [41.23456, 33.1], mouthWidth: 6.5 })
  assert.deepEqual(request, { poses: ['base', 'busto'], style: { mouthStyle: 'warp', smile: 0.15 },
    hints: { busto: { eyes: [40, 20], mouth: [41.235, 33.1], mouthWidth: 6.5, exact: true } } })
  // A kit switching to warp mouths is rigged whole: a pose without mouths of its own would show none.
  const ink = { ...kit, provenance: [{ ...kit.provenance[0], style: { mouthStyle: 'ink' } }] }
  assert.equal(mouthLineRigRequest(ink, 'busto', { mouth: [41, 33], mouthWidth: 6 }).poses, undefined)
})

test('the zoom is a square window round the mouth and maps points both ways', () => {
  const zoom = mouthZoom({ mouth: [44, 17], mouthWidth: 5 }, 896 / 1152)
  assert.ok(Math.abs(zoom.width * 896 - zoom.height * 1152) < 1e-6, 'square in pixels')
  assert.ok(zoom.x >= 0 && zoom.y >= 0 && zoom.x + zoom.width <= 100 && zoom.y + zoom.height <= 100)
  const [fx, fy] = imageToZoom(zoom, 44, 17)
  assert.ok(fx > 40 && fx < 60 && fy > 30 && fy < 50, 'the mouth near the middle, more room under it')
  const [x, y] = zoomToImage(zoom, fx / 100, fy / 100)
  assert.ok(Math.abs(x - 44) < 1e-9 && Math.abs(y - 17) < 1e-9)
  const edge = mouthZoom({ mouth: [2, 98], mouthWidth: 5 }, 1)
  assert.ok(edge.x === 0 && edge.y + edge.height <= 100, 'kept inside the image')
})
