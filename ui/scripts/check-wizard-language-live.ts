import assert from 'node:assert/strict'
import { buildAgentTurnPrompt, HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge'
import {
  HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
  parseAgentTurn,
  type AgentAppSnapshot,
} from '../src/features/agent/agentActions'

const baseUrl = String(process.env.HOCUSPOCUS_BASE_URL || '').replace(/\/$/, '')
if (!baseUrl) throw new Error('Set HOCUSPOCUS_BASE_URL to the exact local HocusPocus URL.')
if (!/^https?:\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$/i.test(baseUrl)) {
  throw new Error('This check only calls a loopback HocusPocus server.')
}

const request = 'Réponds-moi en français. Prépare une vidéo en anglais où le magicien dit exactement "¡Hola, mundo!" en espagnol. Ne génère rien.'
const app = {
  interface_language: 'de',
  context: {},
  current: {},
  available_video_models: [],
} as unknown as AgentAppSnapshot
const response = await fetch(`${baseUrl}/api/v1/llm/generate`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    system_prompt: HOCUSPOCUS_AGENT_SYSTEM_PROMPT,
    prompt: buildAgentTurnPrompt('language_contract_check', [{ role: 'user', text: request }], [], app),
    max_new_tokens: 1_400,
    temperature: 0.1,
    json_schema: HOCUSPOCUS_AGENT_RESPONSE_SCHEMA,
  }),
})
if (!response.ok) throw new Error(`LLM endpoint returned ${response.status}: ${await response.text()}`)
const payload = await response.json() as { text?: string }
const turn = parseAgentTurn(String(payload.text || ''))
const action = turn.actions.find(item => item.type === 'prepare_video')
assert.ok(action && action.type === 'prepare_video', 'MiniMax did not choose prepare_video.')
assert.equal(turn.actions.some(item => item.type === 'start_generation'), false, 'Negated generation was not respected.')
assert.equal(turn.conversationLanguage, 'fr')
assert.equal(action.languageIntent?.technicalPromptLanguage, 'en')
assert.match(action.languageIntent?.spokenLanguage || '', /^(?:es(?:-[a-z0-9]+)?|.*espa|.*spanish)/i)
assert.ok(action.languageIntent?.verbatimSegments.some(segment => (
  segment.kind === 'dialogue' && segment.text === '¡Hola, mundo!'
)), 'The exact Spanish dialogue was not preserved.')

console.log(JSON.stringify({
  ok: true,
  replyLanguage: turn.conversationLanguage,
  action: action.type,
  contentLanguage: action.languageIntent?.contentLanguage,
  spokenLanguage: action.languageIntent?.spokenLanguage,
  technicalPromptLanguage: action.languageIntent?.technicalPromptLanguage,
  exactDialogue: action.languageIntent?.verbatimSegments[0]?.text,
}, null, 2))
