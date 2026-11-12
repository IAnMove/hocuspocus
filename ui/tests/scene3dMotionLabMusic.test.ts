import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Mesh, MeshStandardMaterial } from 'three'
import { buildBouncingBall, buildMusicMachine } from '../src/features/scene3d/motionlab/musicSets'
import { hasMotionLabMusic, MUSIC_SAMPLE_RATE, scheduleMotionLabMusic } from '../src/features/scene3d/motionlab/musicAudio'
import { BALL_RADIUS, beatSeconds, HAMMER_RADIUS, KEY_DEPTH, musicContact, musicContacts, PLATFORM_DEPTH,
  platformPosition } from '../src/features/scene3d/motionlab/musicTimeline'
import { DEFAULT_MOTION_LAB, type MotionLabHandle, type MotionLabSettings } from '../src/features/scene3d/motionlab/types'

const settings: MotionLabSettings = { ...DEFAULT_MOTION_LAB, bpm: 120, seed: 19, amplitude: 1.5, speed: 1, volume: .7 }
const near = (a: number, b: number) => assert.ok(Math.abs(a - b) < 1e-9, a + ' differs from ' + b)

function pose(handle: MotionLabHandle, seconds: number) {
  handle.update(seconds)
  handle.root.updateMatrixWorld(true)
  const result: unknown[] = []
  handle.root.traverse(object => {
    result.push([object.name, [...object.matrixWorld.elements],
      object instanceof Mesh && object.material instanceof MeshStandardMaterial ? object.material.emissiveIntensity : 0])
  })
  return result
}

test('every scheduled ball note coincides with physical platform contact at different tempos', () => {
  for (const speed of [.1, 1, 3]) {
    const value = { ...settings, speed, bpm: 173 }, handle = buildBouncingBall(value)
    for (let index = 0; index < 24; index++) {
      const event = musicContact('motion-bouncing-ball', value, index)
      handle.update(event.seconds)
      const ball = handle.root.getObjectByName('motion-ball')!, at = platformPosition(value, event.lane)
      near(ball.position.x, at[0]); near(ball.position.z, at[2])
      near(ball.position.y - BALL_RADIUS, at[1] + PLATFORM_DEPTH / 2)
      const key = handle.root.getObjectByName('motion-platform-' + event.lane) as Mesh
      near((key.material as MeshStandardMaterial).emissiveIntensity, .675)
    }
    handle.dispose()
  }
})

test('the machine hammers meet their bars on the audible beat, and lift between their contacts', () => {
  const handle = buildMusicMachine(settings)
  for (const event of musicContacts('motion-music-machine', settings, 0, 6)) {
    handle.update(event.seconds)
    const ball = handle.root.getObjectByName('motion-hammer-' + event.lane)!
    const key = handle.root.getObjectByName('motion-key-' + event.lane)!
    near(ball.position.y - HAMMER_RADIUS, key.position.y + KEY_DEPTH / 2)
    handle.update(event.seconds + beatSeconds(settings) * 2)
    near(ball.position.y - HAMMER_RADIUS, key.position.y + KEY_DEPTH / 2 + settings.amplitude)
  }
  handle.dispose()
})

test('seeking backwards reproduces all transforms and key flashes without creating geometry', () => {
  for (const build of [buildBouncingBall, buildMusicMachine]) {
    const handle = build(settings), other = build(settings)
    const wanted = pose(handle, .375)
    pose(handle, 42.917)
    assert.deepEqual(pose(handle, .375), wanted)
    assert.deepEqual(pose(other, .375), wanted)
    assert.ok(handle.root.children.length < 60)
    handle.dispose(); other.dispose()
  }
})

test('disposal releases each shared geometry and material once; density does not multiply the mechanism', () => {
  for (const build of [buildBouncingBall, buildMusicMachine]) {
    const handle = build({ ...settings, density: 3000 }), low = build({ ...settings, density: 200 })
    assert.equal(handle.root.children.length, low.root.children.length)
    const resources = new Set<{ addEventListener: (type: 'dispose', callback: () => void) => void }>()
    handle.root.traverse(object => {
      if (!(object instanceof Mesh)) return
      resources.add(object.geometry)
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) resources.add(material)
    })
    let disposed = 0
    for (const resource of resources) resource.addEventListener('dispose', () => disposed++)
    handle.dispose(); handle.dispose()
    assert.equal(disposed, resources.size)
    assert.equal(handle.root.children.length, 0)
    low.dispose()
  }
})

class FakeSource {
  buffer: AudioBuffer | null = null
  playbackRate = { value: 1 }
  onended: (() => void) | null = null
  starts: number[][] = []
  connections: unknown[] = []
  disconnects = 0
  connect(destination: unknown) { this.connections.push(destination) }
  disconnect() { this.disconnects++ }
  start(...args: number[]) { this.starts.push(args) }
}

class FakeContext {
  sampleRate = 48000
  currentTime = 7
  synthesisDelay = 0
  destination = {}
  buffers: { samples: Float32Array; rate: number; channels: number }[] = []
  sources: FakeSource[] = []
  createBuffer(channels: number, length: number, rate: number) {
    this.currentTime += this.synthesisDelay
    const samples = new Float32Array(length)
    this.buffers.push({ samples, rate, channels })
    return { getChannelData: () => samples, sampleRate: rate, duration: length / rate, length, numberOfChannels: channels }
  }
  createBufferSource() {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }
  audio() { return this as unknown as BaseAudioContext }
}

test('only the two music mechanisms with sound enabled and positive volume allocate audio', () => {
  const context = new FakeContext()
  for (const kind of [undefined, 'motion-particle-morph', 'bouncing-ball', 'motion-seasonal-carriage']) {
    assert.equal(hasMotionLabMusic(kind, settings), false)
    assert.deepEqual(scheduleMotionLabMusic(context.audio(), kind, settings, 4), [])
  }
  for (const value of [{ ...settings, sound: false }, { ...settings, volume: 0 }]) {
    assert.equal(hasMotionLabMusic('motion-music-machine', value), false)
    assert.deepEqual(scheduleMotionLabMusic(context.audio(), 'motion-music-machine', value, 4), [])
  }
  assert.equal(hasMotionLabMusic('motion-bouncing-ball'), true)
  assert.equal(context.buffers.length, 0)
  assert.equal(context.sources.length, 0)
})

test('seek audio equals the original timeline crop, including the earlier note tail', () => {
  for (const kind of ['motion-bouncing-ball', 'motion-music-machine']) {
    const full = new FakeContext(), crop = new FakeContext()
    scheduleMotionLabMusic(full.audio(), kind, settings, 2)
    const sources = scheduleMotionLabMusic(crop.audio(), kind, settings, 2, 2, .125)
    const whole = full.buffers[0].samples, part = crop.buffers[0].samples
    assert.deepEqual(part, whole.slice(MUSIC_SAMPLE_RATE * .125))
    assert.ok(part.subarray(0, 500).some(value => Math.abs(value) > .001), 'a seek preserves the ringing earlier contact')
    assert.equal(sources.length, 1)
    assert.equal(crop.sources[0].playbackRate.value, 2)
    assert.deepEqual(crop.sources[0].starts, [[7, 0, 1.875]])
    near(crop.sources[0].starts[0][2] / crop.sources[0].playbackRate.value, .9375)
    crop.sources[0].onended!()
    assert.equal(crop.sources[0].disconnects, 1)
  }
})

test('rendered music is deterministic, responds to seed and volume, and stays within safe sample bounds', () => {
  const full = new FakeContext(), again = new FakeContext(), quieter = new FakeContext(), variant = new FakeContext()
  scheduleMotionLabMusic(full.audio(), 'motion-music-machine', settings, 4)
  scheduleMotionLabMusic(again.audio(), 'motion-music-machine', settings, 4)
  scheduleMotionLabMusic(quieter.audio(), 'motion-music-machine', { ...settings, volume: settings.volume / 2 }, 4)
  scheduleMotionLabMusic(variant.audio(), 'motion-music-machine', { ...settings, seed: 5 }, 4)
  const samples = full.buffers[0].samples
  assert.deepEqual(samples, again.buffers[0].samples)
  assert.notDeepEqual(samples, variant.buffers[0].samples)
  assert.deepEqual(quieter.buffers[0].samples, samples.map(value => value / 2))
  assert.ok(samples.every(value => Number.isFinite(value) && Math.abs(value) <= 1))
  assert.equal(samples[0], 0, 'the attack begins without a discontinuity')
})

test('live synthesis time skips the elapsed scene audio while the offline clock retains the full crop', () => {
  const live = new FakeContext(), offline = new FakeContext()
  live.synthesisDelay = .125
  scheduleMotionLabMusic(live.audio(), 'motion-bouncing-ball', settings, 2, 2, .5)
  scheduleMotionLabMusic(offline.audio(), 'motion-bouncing-ball', settings, 2, 2, .5)
  assert.deepEqual(live.buffers[0].samples, offline.buffers[0].samples)
  assert.deepEqual(live.sources[0].starts, [[7.125, .25, 1.25]])
  assert.deepEqual(offline.sources[0].starts, [[7, 0, 1.5]])
  const expired = new FakeContext()
  expired.synthesisDelay = 1
  assert.deepEqual(scheduleMotionLabMusic(expired.audio(), 'motion-music-machine', settings, 1, 1, .8), [])
  assert.equal(expired.sources.length, 0, 'an expired scene must not leave a connected source')
})

test('long schedules allocate one bounded mono buffer, regardless of note count or density', () => {
  const context = new FakeContext()
  context.sampleRate = 32 // inspect the entire 600-second contract without expensive audio work in this test
  scheduleMotionLabMusic(context.audio(), 'motion-music-machine', { ...settings, bpm: 240, speed: 3, density: 3000 }, 600)
  assert.equal(context.sources.length, 1)
  assert.equal(context.buffers.length, 1)
  assert.equal(context.buffers[0].channels, 1)
  assert.equal(context.buffers[0].samples.length, 600 * 32)
  assert.equal(MUSIC_SAMPLE_RATE * 600 * Float32Array.BYTES_PER_ELEMENT, 38_400_000)
})

test('scene boundaries and invalid audio windows cannot schedule extra contacts or unbounded buffers', () => {
  assert.deepEqual(musicContacts('motion-bouncing-ball', settings, .5, 1.5).map(contact => contact.seconds), [.5, 1])
  const context = new FakeContext()
  for (const [duration, speed, offset] of [[601, 1, 0], [NaN, 1, 0], [1, 0, 0], [1, Infinity, 0], [1, 1, -1], [1, 1, 1]]) {
    assert.throws(() => scheduleMotionLabMusic(context.audio(), 'motion-bouncing-ball', settings, duration, speed, offset), /Invalid/)
  }
  assert.equal(context.buffers.length, 0)
})
