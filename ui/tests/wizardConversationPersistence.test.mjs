import assert from 'node:assert/strict'
import test from 'node:test'

const {
  saveWizardConversationWithRecovery,
  mergeWizardConversationSnapshots,
} = await import('../src/features/agent/wizardConversationPersistence.ts')
const {
  WizardConversationRequestError,
  fetchWizardConversation,
} = await import('../src/api/wizard.ts')
const {
  isWizardConversationWriteCurrent,
  hasExclusiveWizardMessages,
  shouldFollowWizardWorkspace,
} = await import('../src/features/agent/wizardConversationSync.ts')

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function payload(revision, ids, prefix = '') {
  return {
    version: 1,
    revision,
    messages: ids.map((id, index) => ({
      id,
      role: index % 2 ? 'assistant' : 'user',
      text: `${prefix}${id}`,
      createdAt: index + 1,
      executionKey: `${prefix}${id}-execution`,
      jobLinks: [{ taskId: `${prefix}${id}-task`, pipelineId: '' }],
    })),
    executions: [],
  }
}

function revisionConflict(expected, current) {
  return new WizardConversationRequestError(
    `expected ${expected}, current ${current}`,
    409,
    {
      code: 'wizard_conversation_revision_conflict',
      expectedRevision: expected,
      currentRevision: current,
    },
  )
}

test('two writers preserve both Wizard turns exactly once after one CAS conflict', async () => {
  let canonical = payload(0, [])
  const calls = []
  const transport = {
    async fetch(workspace) {
      calls.push({ method: 'fetch', workspace })
      return clone(canonical)
    },
    async save(workspace, conversation) {
      calls.push({ method: 'save', workspace, conversation: clone(conversation) })
      if (conversation.revision !== canonical.revision) {
        throw revisionConflict(conversation.revision, canonical.revision)
      }
      canonical = { ...clone(conversation), revision: canonical.revision + 1 }
      return clone(canonical)
    },
  }

  const first = await saveWizardConversationWithRecovery('workspace-a', payload(0, ['a-user', 'a-assistant'], 'A-'), transport)
  const second = await saveWizardConversationWithRecovery('workspace-a', payload(0, ['b-user', 'b-assistant'], 'B-'), transport)

  assert.equal(first.merged, false)
  assert.equal(second.merged, true)
  assert.equal(canonical.revision, 2)
  assert.deepEqual(canonical.messages.map(message => message.id), [
    'a-user', 'a-assistant', 'b-user', 'b-assistant',
  ])
  assert.equal(new Set(canonical.messages.map(message => message.id)).size, 4)
  assert.deepEqual(canonical.messages.map(message => message.executionKey), [
    'A-a-user-execution', 'A-a-assistant-execution',
    'B-b-user-execution', 'B-b-assistant-execution',
  ])
  assert.deepEqual(calls.map(call => `${call.method}:${call.workspace}`), [
    'save:workspace-a', 'save:workspace-a', 'fetch:workspace-a', 'save:workspace-a',
  ])

  const repeatedMerge = mergeWizardConversationSnapshots(second.conversation, canonical)
  assert.deepEqual(repeatedMerge.messages.map(message => message.id), canonical.messages.map(message => message.id))
})

test('second conflict is surfaced after one recovery retry and never loops', async () => {
  let saves = 0
  let fetches = 0
  const transport = {
    async fetch() {
      fetches += 1
      return payload(4, ['remote-user', 'remote-assistant'], 'remote-')
    },
    async save(_workspace, conversation) {
      saves += 1
      throw revisionConflict(conversation.revision, 4)
    },
  }

  await assert.rejects(
    saveWizardConversationWithRecovery('workspace-a', payload(0, ['local-user', 'local-assistant'], 'local-'), transport),
    error => error instanceof WizardConversationRequestError && error.status === 409,
  )
  assert.equal(saves, 2)
  assert.equal(fetches, 1)
})

test('non-recoverable 4xx is surfaced without a refetch or retry', async () => {
  let saves = 0
  let fetches = 0
  const transport = {
    async fetch() {
      fetches += 1
      return payload(0, [])
    },
    async save() {
      saves += 1
      throw new WizardConversationRequestError(
        'conversation payload is invalid',
        400,
        { detail: 'conversation payload is invalid' },
      )
    },
  }

  await assert.rejects(
    saveWizardConversationWithRecovery('workspace-a', payload(0, ['local-user']), transport),
    error => error instanceof WizardConversationRequestError && error.status === 400,
  )
  assert.equal(saves, 1)
  assert.equal(fetches, 0)
})

test('conversation HTTP errors retain nested API detail and status', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: {
      code: 'wizard_conversation_revision_conflict',
      message: 'expected 2, current 3',
      expectedRevision: 2,
      currentRevision: 3,
    },
  }), {
    status: 409,
    headers: { 'content-type': 'application/json' },
  })
  try {
    await assert.rejects(
      fetchWizardConversation('workspace-a'),
      error => error instanceof WizardConversationRequestError
        && error.status === 409
        && error.code === 'wizard_conversation_revision_conflict'
        && error.message === 'expected 2, current 3',
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('workspace changes never rebind an in-flight conversation write', () => {
  assert.equal(shouldFollowWizardWorkspace({
    activeWorkspace: 'workspace-b',
    conversationWorkspace: 'workspace-a',
    busy: true,
  }), false)
  assert.equal(shouldFollowWizardWorkspace({
    activeWorkspace: 'workspace-b',
    conversationWorkspace: 'workspace-a',
    busy: false,
  }), true)
  assert.equal(isWizardConversationWriteCurrent('workspace-a', 'workspace-b'), false)
  assert.equal(isWizardConversationWriteCurrent('workspace-a', 'workspace-a'), true)
})

test('a conflict response cannot suppress persistence of a newer visible turn', () => {
  const saved = payload(3, ['old-user', 'old-assistant']).messages
  const withNewTurn = [
    ...saved,
    { id: 'new-user', role: 'user', text: 'new request', createdAt: 3 },
  ]

  assert.equal(hasExclusiveWizardMessages(withNewTurn, saved), true)
  assert.equal(hasExclusiveWizardMessages(saved, saved), false)
})
