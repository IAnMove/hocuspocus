import assert from 'node:assert/strict'
import test from 'node:test'
import { createVideoJsDocument, createVideoJsScene } from '../src/features/videojs/document.ts'
import {
  VideoJsLlmError,
  applyVideoJsResponse,
  buildVideoJsPrompt,
  parseVideoJsResponse,
  runVideoJsLlm,
  serializeVideoJsForLlm,
} from '../src/features/videojs/llm.ts'
import { VIDEOJS_SYSTEM_PROMPT } from '../src/features/videojs/promptGuide.ts'

const answer = `<think>I will plan three scenes <scene>not this</scene></think>
Sure! Here is the video:
\`\`\`xml
<video title="Launch day">
<theme primary="#ff0066" background="#000000" text="javascript:alert(1)" />
<scene title="Hello" kind="2d" duration="4" transition="wipe">
\`\`\`js
return { render({ ctx, kit }) { kit.draw.background(ctx) } }
\`\`\`
</scene>
<scene id="keep" title='Orbit' kind="3d" duration="6">
return { render() {} }
</scene>
</video>
\`\`\``

test('the tolerant parser strips thinking, prose and code fences', () => {
  const parsed = parseVideoJsResponse(answer)
  assert.equal(parsed.complete, true)
  assert.equal(parsed.title, 'Launch day')
  assert.equal(parsed.theme?.primary, '#ff0066')
  assert.equal(parsed.scenes.length, 2)
  assert.equal(parsed.scenes[0].code, 'return { render({ ctx, kit }) { kit.draw.background(ctx) } }')
  assert.equal(parsed.scenes[0].transition, 'wipe')
  assert.equal(parsed.scenes[1].id, 'keep')
  assert.equal(parsed.scenes[1].title, 'Orbit')
  assert.equal(parseVideoJsResponse('<video><scene>return {}</scene>').complete, false)
})

test('create replaces scenes, keeps format and records the request', () => {
  const document = createVideoJsDocument({ width: 1080, height: 1920, fps: 60 })
  const next = applyVideoJsResponse(document, { mode: 'create', request: '  A launch video  ' }, answer)
  assert.equal(next.width, 1080)
  assert.equal(next.fps, 60)
  assert.equal(next.title, 'Launch day')
  assert.equal(next.prompt, 'A launch video')
  assert.equal(next.theme.primary, '#ff0066')
  assert.equal(next.theme.text, document.theme.text, 'invalid colors fall back to the current theme')
  assert.deepEqual(next.scenes.map(scene => scene.kind), ['2d', '3d'])
  assert.notEqual(next.scenes[1].id, 'keep', 'create never trusts ids from the LLM')
  assert.equal(document.scenes.length, 1, 'input document is not mutated')
})

test('adjusting the whole video keeps matching ids and rejects truncated answers', () => {
  const document = createVideoJsDocument({
    scenes: [createVideoJsScene('2d', { id: 'keep', title: 'Old', duration: 3 }), createVideoJsScene('2d', { id: 'drop' })],
  })
  const next = applyVideoJsResponse(document, { mode: 'adjust-video', instruction: 'x' }, answer)
  assert.equal(next.scenes.length, 2)
  assert.equal(next.scenes[1].id, 'keep')
  assert.equal(next.scenes[1].duration, 6)
  assert.equal(next.scenes.some(scene => scene.id === 'drop'), false)
  assert.throws(
    () => applyVideoJsResponse(document, { mode: 'adjust-video', instruction: 'x' }, answer.replace('</video>', '')),
    (error: unknown) => error instanceof VideoJsLlmError && error.code === 'truncated',
  )
  assert.throws(
    () => applyVideoJsResponse(document, { mode: 'create', request: 'x' }, 'I cannot help with that'),
    (error: unknown) => error instanceof VideoJsLlmError && error.code === 'empty',
  )
})

test('scene adjustments and fixes only replace the target scene', () => {
  const document = createVideoJsDocument({
    scenes: [createVideoJsScene('2d', { id: 'a', code: 'return { render() { a() } }' }), createVideoJsScene('2d', { id: 'b', title: 'Keep title', duration: 5 })],
  })
  const reply = '<video><scene id="other" kind="3d">return { render() { fixed() } }</scene></video>'
  const next = applyVideoJsResponse(document, { mode: 'fix-scene', sceneId: 'b', error: { sceneId: 'b', phase: 'render', message: 'boom' } }, reply)
  assert.equal(next.scenes[0], document.scenes[0])
  assert.equal(next.scenes[1].id, 'b')
  assert.equal(next.scenes[1].title, 'Keep title')
  assert.equal(next.scenes[1].duration, 5)
  assert.equal(next.scenes[1].kind, '3d')
  assert.equal(next.scenes[1].code, 'return { render() { fixed() } }')
  assert.throws(() => applyVideoJsResponse(document, { mode: 'adjust-scene', sceneId: 'gone', instruction: 'x' }, reply), VideoJsLlmError)
})

test('prompts carry format, current code, ids and the error to fix', async () => {
  const document = createVideoJsDocument({ width: 1080, height: 1080, scenes: [createVideoJsScene('2d', { id: 'intro', code: 'return { render() { title() } }' })] })
  const adjust = buildVideoJsPrompt(document, { mode: 'adjust-video', instruction: 'warmer' })
  assert.match(adjust, /1080x1080 pixels \(square\)/)
  assert.match(adjust, /id="intro"/)
  assert.match(adjust, /title\(\)/)
  assert.match(adjust, /warmer/)
  const fix = buildVideoJsPrompt(document, { mode: 'fix-scene', sceneId: 'intro', error: { sceneId: 'intro', phase: 'render', message: 'TypeError: x', line: 4 } })
  assert.match(fix, /FIX THIS ERROR \(render, line 4\)/)
  assert.match(fix, /exactly one <scene> with id="intro"/)
  assert.match(serializeVideoJsForLlm(document), /^<video title=".*">\n<theme /)
  let seen: { system_prompt: string; max_new_tokens: number } | null = null
  const next = await runVideoJsLlm(document, { mode: 'create', request: 'demo' }, async params => {
    seen = params
    return answer
  })
  assert.equal(seen!.system_prompt, VIDEOJS_SYSTEM_PROMPT)
  assert.ok(seen!.max_new_tokens >= 8000)
  assert.equal(next.scenes.length, 2)
})
