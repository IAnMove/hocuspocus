import test from 'node:test'
import assert from 'node:assert/strict'
import { fulfillSeekable } from '../e2e/helpers/seekableMedia.ts'

function routeWith(range) {
  const calls = []
  return {
    calls,
    request: () => ({ headers: () => (range ? { range } : {}) }),
    fulfill: options => { calls.push(options) },
  }
}

test('a full GET keeps Accept-Ranges so Chrome can seek afterwards', async () => {
  const route = routeWith()
  await fulfillSeekable(Buffer.from('abcdefghij'), 'video/webm')(route)
  assert.equal(route.calls[0].status, 200)
  assert.equal(route.calls[0].headers['Accept-Ranges'], 'bytes')
  assert.equal(route.calls[0].body.toString(), 'abcdefghij')
})

test('an open Range of the whole file stays a 200 so Chromium can start playback', async () => {
  const route = routeWith('bytes=0-')
  await fulfillSeekable(Buffer.from('abcdefghij'), 'video/webm')(route)
  assert.equal(route.calls[0].status, 200)
  assert.equal(route.calls[0].body.toString(), 'abcdefghij')
})

test('a Range GET returns the 206 slice Chrome needs for currentTime', async () => {
  const route = routeWith('bytes=2-5')
  await fulfillSeekable(Buffer.from('abcdefghij'), 'video/webm')(route)
  assert.equal(route.calls[0].status, 206)
  assert.equal(route.calls[0].headers['Content-Range'], 'bytes 2-5/10')
  assert.equal(route.calls[0].body.toString(), 'cdef')
})
