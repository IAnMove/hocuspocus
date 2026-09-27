import assert from 'node:assert/strict'
import test from 'node:test'
import { generateBlockedCopy } from '../src/lib/generateButtonGate.ts'

const t = ((key: string) => key) as import('i18next').TFunction<'studio'>

test('image generation without a prompt is blocked before submit', () => {
  const copy = generateBlockedCopy({ needsPrompt: true, t })
  assert.equal(copy.label, 'generate.addPrompt')
  assert.equal(copy.title, 'generate.addPromptHint')
})
