import assert from 'node:assert/strict'
import test from 'node:test'
import { videosSettled, type SettlingVideo } from '../src/lib/scene2d/videoSettle'

class FakeVideo extends EventTarget {
  constructor(public seeking: boolean, public readyState: number) { super() }
}
const asVideo = (video: FakeVideo) => video as unknown as SettlingVideo

test('a video that already shows its frame does not hold the export frame', async () => {
  await videosSettled([asVideo(new FakeVideo(false, 4))], 10_000)
})

test('an export frame waits for every video to land its seek, and a stuck one gives up after the timeout', async () => {
  const seeking = new FakeVideo(true, 1)
  let settled = false
  const waiting = videosSettled([asVideo(seeking), asVideo(new FakeVideo(false, 2))], 10_000).then(() => { settled = true })
  await new Promise(resolve => setTimeout(resolve, 5))
  assert.equal(settled, false, 'painting now would drop the video layer')
  seeking.seeking = false; seeking.readyState = 4
  seeking.dispatchEvent(new Event('seeked'))
  await waiting
  assert.equal(settled, true)
  const started = Date.now()
  await videosSettled([asVideo(new FakeVideo(true, 1))], 20)
  assert.ok(Date.now() - started < 1000, 'a video that never lands its seek does not stall the export')
})
