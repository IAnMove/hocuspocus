import assert from 'node:assert/strict'
import test from 'node:test'
import {
  VIDEOJS_LIMITS,
  createVideoJsDocument,
  createVideoJsScene,
  duplicateVideoJsScene,
  moveVideoJsScene,
  normalizeVideoJsDocument,
  updateVideoJsScene,
  videoJsDuration,
  videoJsFormatOf,
  videoJsSceneFocusTime,
  videoJsSpanAt,
} from '../src/features/videojs/document.ts'
import { videoJsExampleDocument } from '../src/features/videojs/examples.ts'
import { mergeSceneErrors, sanitizeSceneErrors, videoJsRenderSpec, videoJsSandboxSrcdoc, VIDEOJS_SANDBOX_CSP } from '../src/features/videojs/sandbox.ts'
import { commitHistory, undoHistory } from '../src/features/videojs/useVideoJsDocument.ts'

test('untrusted Video JS JSON is normalized into safe bounds', () => {
  const document = normalizeVideoJsDocument({
    title: 42,
    width: 99999,
    height: 'x',
    fps: 24,
    theme: { primary: 'url(javascript:alert(1))', text: '#fff', font: 'Inter; } body { color: red' },
    scenes: [
      { id: 'a', kind: '3D', duration: 999, transition: 'spin', transitionDuration: 9, code: 'return { render() {} }' },
      { id: 'a', kind: 'weird', duration: -3, code: 7 },
      { id: '../../etc', duration: '2.5' },
    ],
  })
  assert.equal(document.schema, 'hocuspocus.videojs/v1')
  assert.equal(document.title, 'Untitled video')
  assert.equal(document.width, 3840)
  assert.equal(document.height, 1080)
  assert.equal(document.fps, 30)
  assert.equal(document.theme.primary, '#7c5cff')
  assert.equal(document.theme.text, '#fff')
  assert.doesNotMatch(document.theme.font, /[;{}]/)
  const [first, second, third] = document.scenes
  assert.equal(first.kind, '3d')
  assert.equal(first.duration, VIDEOJS_LIMITS.maxSceneSeconds)
  assert.equal(first.transition, 'fade')
  assert.equal(first.transitionDuration, VIDEOJS_LIMITS.maxTransitionSeconds)
  assert.equal(second.kind, '2d')
  assert.equal(second.duration, VIDEOJS_LIMITS.minSceneSeconds)
  assert.equal(second.code, '')
  assert.notEqual(second.id, first.id, 'duplicated ids are replaced')
  assert.match(third.id, /^scene-/, 'ids outside the safe charset are replaced')
  assert.equal(third.duration, 2.5)
})

test('total duration is capped and the timeline resolves scene spans', () => {
  const long = normalizeVideoJsDocument({ scenes: Array.from({ length: 15 }, () => ({ duration: 60, code: 'x' })) })
  assert.equal(videoJsDuration(long), VIDEOJS_LIMITS.maxVideoSeconds)
  const document = createVideoJsDocument({
    scenes: [createVideoJsScene('2d', { id: 'one', duration: 2 }), createVideoJsScene('3d', { id: 'two', duration: 3 })],
  })
  assert.equal(videoJsDuration(document), 5)
  assert.equal(videoJsSpanAt(document, 0)?.scene.id, 'one')
  assert.equal(videoJsSpanAt(document, 1.999)?.scene.id, 'one')
  assert.equal(videoJsSpanAt(document, 2)?.scene.id, 'two')
  assert.equal(videoJsSpanAt(document, 2)?.start, 2)
  assert.equal(videoJsSpanAt(document, 50)?.scene.id, 'two', 'the last scene holds after the end')
  assert.equal(videoJsSpanAt({ scenes: [] }, 1), null)
  assert.equal(videoJsSceneFocusTime(document, 'one'), 0.01)
  assert.equal(videoJsSceneFocusTime(document, 'two'), 2.51, 'selection skips the entry fade')
  assert.equal(videoJsSceneFocusTime(document, 'missing'), 0)
  assert.equal(videoJsFormatOf({ width: 1080, height: 1920 }), 'portrait')
  assert.equal(videoJsFormatOf({ width: 1080, height: 1080 }), 'square')
})

test('scene operations return new documents and keep ids stable', () => {
  const document = createVideoJsDocument({
    scenes: ['a', 'b', 'c'].map(id => createVideoJsScene('2d', { id, title: id.toUpperCase() })),
  })
  const moved = moveVideoJsScene(document, 'c', -1)
  assert.deepEqual(moved.scenes.map(scene => scene.id), ['a', 'c', 'b'])
  assert.deepEqual(document.scenes.map(scene => scene.id), ['a', 'b', 'c'])
  assert.equal(moveVideoJsScene(document, 'a', -1), document)
  const duplicated = duplicateVideoJsScene(document, 'b')
  assert.equal(duplicated.scenes.length, 4)
  assert.equal(duplicated.scenes[2].title, 'B copy')
  assert.notEqual(duplicated.scenes[2].id, 'b')
  const updated = updateVideoJsScene(document, 'b', { id: 'hijack', duration: 7, kind: '3d' })
  assert.equal(updated.scenes[1].id, 'b')
  assert.equal(updated.scenes[1].duration, 7)
  assert.equal(updated.scenes[1].kind, '3d')
})

test('undo history coalesces rapid edits with the same key', () => {
  const base = createVideoJsDocument()
  let state = { workspace: 'default', document: base, past: [] as typeof base[], lastKey: null as string | null, lastAt: 0 }
  const titled = (title: string) => ({ ...state.document, title })
  state = commitHistory(state, titled('A'), 'title', 1000)
  state = commitHistory(state, titled('AB'), 'title', 1500)
  state = commitHistory(state, titled('ABC'), 'title', 1900)
  assert.equal(state.past.length, 1)
  state = commitHistory(state, titled('ABC!'), null, 1950)
  assert.equal(state.past.length, 2)
  state = undoHistory(state)
  assert.equal(state.document.title, 'ABC')
  state = undoHistory(state)
  assert.equal(state.document, base)
  assert.equal(undoHistory(state), state)
})

test('sandbox document is isolated by CSP and only carries render fields', () => {
  assert.match(VIDEOJS_SANDBOX_CSP, /connect-src 'none'/)
  assert.match(VIDEOJS_SANDBOX_CSP, /default-src 'none'/)
  assert.doesNotMatch(VIDEOJS_SANDBOX_CSP, /allow-same-origin|'self'/)
  const srcdoc = videoJsSandboxSrcdoc('console.log("</script><img src=x>")')
  assert.match(srcdoc, /http-equiv="Content-Security-Policy"/)
  assert.equal(srcdoc.match(/<\/script>/g)?.length, 1, 'host source cannot close the script element early')
  const example = videoJsExampleDocument()
  const spec = videoJsRenderSpec(example)
  assert.deepEqual(Object.keys(spec).sort(), ['fps', 'height', 'scenes', 'theme', 'width'])
  assert.equal(JSON.stringify(spec).includes(example.scenes[0].title), false)
})

test('sandbox errors are sanitized and merged per scene', () => {
  const errors = sanitizeSceneErrors([
    { sceneId: 'a', phase: 'render', message: 'x'.repeat(5000), line: 3 },
    { sceneId: 7, phase: 'evil', message: null, line: -1 },
    'nope',
  ])
  assert.equal(errors.length, 2)
  assert.equal(errors[0].message.length, 1000)
  assert.deepEqual(errors[1], { sceneId: '', phase: 'runtime', message: 'Unknown error' })
  const current = [{ sceneId: 'a', phase: 'render' as const, message: 'boom' }]
  assert.equal(mergeSceneErrors(current, [{ sceneId: 'a', phase: 'render', message: 'boom' }]), current)
  assert.equal(mergeSceneErrors(current, [{ sceneId: 'b', phase: 'setup', message: 'bad' }]).length, 2)
})
