import assert from 'node:assert/strict'
import test from 'node:test'

const { resolveWizardPendingAnswer } = await import('../src/features/agent/AgentAssistantPanel.tsx')

const pending = {
  workflowId: 'workflow-1', stepId: 'choose-audio', reason: 'Choose exact audio',
  fields: ['audioOutputName'],
  options: [
    { value: 'song-v1.wav', label: 'Versión 1' },
    { value: 'song-v2.wav', label: 'Versión 2' },
  ],
  recommended: 'song-v2.wav', resolvedEntityIds: {}, answer: null,
  version: 1, requestedAt: 1, createdAt: 1, updatedAt: 1, answeredAt: 0,
}

test('chat answers a durable question by label or exact value without invoking an LLM', () => {
  assert.deepEqual(resolveWizardPendingAnswer(pending, 'Versión 2'), { audioOutputName: 'song-v2.wav' })
  assert.deepEqual(resolveWizardPendingAnswer(pending, 'song-v1.wav'), { audioOutputName: 'song-v1.wav' })
  assert.equal(resolveWizardPendingAnswer(pending, 'cualquier otra cosa'), null)
})

test('free fields and multiple explicit field=value answers remain structured', () => {
  const free = { ...pending, options: [], fields: ['sceneName'] }
  assert.deepEqual(resolveWizardPendingAnswer(free, 'Catedral de servidores'), { sceneName: 'Catedral de servidores' })
  const multiple = { ...pending, options: [], fields: ['width', 'height'] }
  assert.deepEqual(resolveWizardPendingAnswer(multiple, 'width=1280, height=720'), { width: '1280', height: '720' })
  assert.equal(resolveWizardPendingAnswer(multiple, '1280 por 720'), null)
})
