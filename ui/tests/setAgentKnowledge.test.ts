import { test } from 'node:test'
import assert from 'node:assert/strict'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
test('the embedded operator points to real prop tools and preserves receipt-based execution',()=>{
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT,/props\.create/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT,/scene3d\.item\.add/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT,/Only execution receipts can certify completion/)
})
