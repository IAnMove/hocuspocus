import assert from 'node:assert/strict'
import test from 'node:test'
import { sceneAudioWavDataUrl } from '../src/features/sceneFx/audioExport.ts'

function fakeBuffer(seconds: number, sampleRate = 48000) {
  const frames = Math.round(seconds * sampleRate)
  const left = Float32Array.from({ length: frames }, (_unused, index) => 0.5 * Math.sin((2 * Math.PI * 440 * index) / sampleRate))
  const right = left.map(value => -value)
  return { sampleRate, numberOfChannels: 2, duration: frames / sampleRate, length: frames, getChannelData: (channel: number) => (channel ? right : left) } as unknown as AudioBuffer
}

test('the owned-browser audio bridge hands over a 32-bit float stereo WAV of the whole mix', async () => {
  const url = await sceneAudioWavDataUrl(fakeBuffer(2))
  assert.match(url, /^data:audio\/wav;base64,/)
  const bytes = Buffer.from(url.split(',')[1]!, 'base64')
  assert.equal(bytes.toString('ascii', 0, 4), 'RIFF')
  assert.equal(bytes.toString('ascii', 8, 12), 'WAVE')
  assert.equal(bytes.readUInt16LE(20), 3, 'IEEE float, so peaks above 0 dBFS reach the server limiter')
  assert.equal(bytes.readUInt16LE(22), 2, 'stereo')
  assert.equal(bytes.readUInt32LE(24), 48000, 'sample rate')
  assert.equal(bytes.readUInt16LE(34), 32, 'bits')
  const dataBytes = bytes.readUInt32LE(40)
  assert.equal(dataBytes / 8 / 48000, 2, 'two seconds')
  const quarter = 48000 / 440 / 4
  const peak = bytes.readFloatLE(44 + Math.round(quarter) * 8)
  assert.ok(Math.abs(peak - 0.5) < 0.01, 'left peak survives exactly')
  assert.equal(bytes.readFloatLE(48 + Math.round(quarter) * 8), -peak, 'right is the inverted channel')
})

test('a mix louder than full scale is not clipped in the file', async () => {
  const loud = fakeBuffer(1)
  const left = loud.getChannelData(0)
  left[10] = 1.7
  const bytes = Buffer.from((await sceneAudioWavDataUrl(loud)).split(',')[1]!, 'base64')
  assert.ok(Math.abs(bytes.readFloatLE(44 + 10 * 8) - 1.7) < 1e-6)
})

test('mixes above the browser bound are refused, as in the browser export', async () => {
  await assert.rejects(sceneAudioWavDataUrl(fakeBuffer(181, 8000)), /180/)
})
