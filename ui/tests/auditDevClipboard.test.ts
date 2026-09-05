import assert from 'node:assert/strict'
import test from 'node:test'
import { formatFailedPromptDump, promptFromMetadata } from '../src/features/auditdev/auditClipboard.ts'

test('failed prompt dump is pasteable into chat', () => {
  const text = formatFailedPromptDump([
    {
      name: 'minimax_h3_abc.mp4',
      jobId: 'abc',
      prompt: 'integrated_multimodal_description: [Shot 1] A wizard says <d>[Spanish] Hola.</d>',
    },
  ])
  assert.match(text, /AUDITDEV_FAILED_PROMPTS/)
  assert.match(text, /file: minimax_h3_abc.mp4/)
  assert.match(text, /job_id: abc/)
  assert.match(text, /<d>\[Spanish\] Hola\.<\/d>/)
})

test('prompt prefers params.prompt then video_prompt', () => {
  assert.equal(
    promptFromMetadata({ params: { prompt: 'A', video_prompt: 'B' } }),
    'A',
  )
  assert.equal(
    promptFromMetadata({ params: { video_prompt: 'B' } }),
    'B',
  )
  assert.equal(promptFromMetadata({ params: null }), '')
})
