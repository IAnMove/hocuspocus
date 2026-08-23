import assert from 'node:assert/strict'
import test from 'node:test'

import { LLM_ACTIVITY_PREVIEW_LIMIT, llmActivityPreview } from '../src/lib/llmActivityPreview.ts'

test('live LLM preview is readable and bounded to the newest text', () => {
  const raw = `${'old '.repeat(500)}\n\n newest   useful   tail `
  const preview = llmActivityPreview(raw)

  assert.equal(preview.length, LLM_ACTIVITY_PREVIEW_LIMIT)
  assert.ok(preview.startsWith('…'))
  assert.ok(preview.endsWith('newest useful tail'))
  assert.equal(preview.includes('\n'), false)
})

test('short previews remain unchanged and an empty budget retains nothing', () => {
  assert.equal(llmActivityPreview('  short   status  '), 'short status')
  assert.equal(llmActivityPreview('secret', 0), '')
})
