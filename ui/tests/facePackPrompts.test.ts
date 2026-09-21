import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fillFacePrompt, FACE_PLANE_REST_PROMPT, parseFacePackStillName, visemePrompt } from '../src/features/scene3d/speech/facePackPrompts'

test('cube-front rest prompt fills the skin token and forbids a round head', () => {
  const text = fillFacePrompt(FACE_PLANE_REST_PROMPT, 'terracotta clay')
  assert.match(text, /terracotta clay/)
  assert.match(text, /front of a cube/)
  assert.match(text, /No circular head/)
  assert.equal(text.includes('{skin}'), false)
})

test('viseme edits only change the mouth', () => {
  assert.match(visemePrompt('A'), /Change only the mouth/)
  assert.match(visemePrompt('O'), /small round O/)
})

test('still filenames map to rest, viseme or expression', () => {
  assert.deepEqual(parseFacePackStillName('rest.png'), { kind: 'rest' })
  assert.deepEqual(parseFacePackStillName('viseme-A.jpg'), { kind: 'viseme', id: 'A' })
  assert.deepEqual(parseFacePackStillName('expr-happy.PNG'), { kind: 'expression', id: 'happy' })
  assert.equal(parseFacePackStillName('hero.png'), undefined)
})
