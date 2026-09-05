import assert from 'node:assert/strict'
import test from 'node:test'
import { extractRewrittenPrompt, workspaceRewriteSystemPrompt } from '../src/features/workspaces/rewrite.ts'

test('workspace rewrite keeps MiniMax fields and the user instruction', () => {
  const system = workspaceRewriteSystemPrompt('quita todos los MC', true)
  assert.match(system, /quita todos los MC/)
  assert.match(system, /subject_definitions/)
  assert.match(system, /Tighten the visual body/)
  assert.match(system, /rapper/)
})

test('extractRewrittenPrompt strips fences and labels', () => {
  assert.equal(
    extractRewrittenPrompt('```text\n[Shot 1] A dwarf forges.\n```', 'fallback'),
    '[Shot 1] A dwarf forges.',
  )
  assert.equal(extractRewrittenPrompt('Prompt: Closed-mouth dwarf', 'fallback'), 'Closed-mouth dwarf')
  assert.equal(extractRewrittenPrompt('   ', 'keep me'), 'keep me')
})
