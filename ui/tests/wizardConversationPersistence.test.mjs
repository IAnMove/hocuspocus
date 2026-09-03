import assert from 'node:assert/strict'
import test from 'node:test'

const {
  saveWizardConversationWithRecovery,
  mergeWizardConversationSnapshots,
  mergeQueuedWizardConversationSnapshots,
  enqueueWizardConversationSave,
  persistQueuedWizardConversation,
  newestWizardConversationSnapshot,
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

test('conversation writes are serialized and a later write sees the confirmed revision', async () => {
  let revision = 0
  let active = 0
  let maximumActive = 0
  const observed = []
  let releaseFirst
  let markFirstStarted
  const firstGate = new Promise(resolve => { releaseFirst = resolve })
  const firstStarted = new Promise(resolve => { markFirstStarted = resolve })

  let chain = Promise.resolve()
  chain = enqueueWizardConversationSave(chain, async () => {
    active += 1
    maximumActive = Math.max(maximumActive, active)
    observed.push(revision)
    markFirstStarted()
    await firstGate
    revision = 1
    active -= 1
  })
  chain = enqueueWizardConversationSave(chain, async () => {
    active += 1
    maximumActive = Math.max(maximumActive, active)
    observed.push(revision)
    revision = 2
    active -= 1
  })

  await firstStarted
  assert.deepEqual(observed, [0])
  releaseFirst()
  await chain
  assert.deepEqual(observed, [0, 1])
  assert.equal(maximumActive, 1)
  assert.equal(revision, 2)
})

test('a stale queued snapshot merges the canonical turn saved by its predecessor', async () => {
  let canonical = payload(0, [])
  const snapshots = new Map()
  const savedPayloads = []
  const transport = {
    async fetch() { return clone(canonical) },
    async save(_workspace, conversation) {
      assert.equal(conversation.revision, canonical.revision)
      savedPayloads.push(clone(conversation))
      canonical = { ...clone(conversation), revision: canonical.revision + 1 }
      return clone(canonical)
    },
  }

  const firstVisible = payload(0, ['first-user', 'first-assistant'])
  const staleSecondEffect = payload(0, ['second-user', 'second-assistant'])
  let chain = Promise.resolve()
  chain = enqueueWizardConversationSave(chain, () => (
    persistQueuedWizardConversation({ workspace: 'workspace-a', captured: firstVisible }, snapshots, transport).then(() => undefined)
  ))
  chain = enqueueWizardConversationSave(chain, () => (
    persistQueuedWizardConversation({ workspace: 'workspace-a', captured: staleSecondEffect }, snapshots, transport).then(() => undefined)
  ))
  await chain

  assert.deepEqual(savedPayloads[1].messages.map(message => message.id), [
    'first-user', 'first-assistant', 'second-user', 'second-assistant',
  ])
  assert.equal(savedPayloads[1].revision, 1)
  assert.deepEqual(snapshots.get('workspace-a'), canonical)
})

test('a queued write persists to its captured workspace after the visible workspace changes', async () => {
  const snapshots = new Map()
  const savedWorkspaces = []
  let visibleWorkspace = 'workspace-a'
  let releaseWrite
  const gate = new Promise(resolve => { releaseWrite = resolve })
  const transport = {
    async fetch() { return payload(0, []) },
    async save(workspace, conversation) {
      await gate
      savedWorkspaces.push(workspace)
      return { ...clone(conversation), revision: 1 }
    },
  }

  let chain = Promise.resolve()
  chain = enqueueWizardConversationSave(chain, () => (
    persistQueuedWizardConversation({ workspace: 'workspace-a', captured: payload(0, ['a-user']) }, snapshots, transport).then(() => undefined)
  ))
  visibleWorkspace = 'workspace-b'
  releaseWrite()
  await chain

  assert.equal(visibleWorkspace, 'workspace-b')
  assert.deepEqual(savedWorkspaces, ['workspace-a'])
  assert.equal(snapshots.get('workspace-a').revision, 1)
})

test('three-way queued merge applies local edits while retaining concurrent turns', () => {
  const base = payload(3, ['shared-user'])
  const local = clone(base)
  local.messages[0].text = 'locally edited'
  const canonical = payload(4, ['shared-user', 'remote-assistant'])
  canonical.messages[0].text = 'old canonical text'

  const merged = mergeQueuedWizardConversationSnapshots(local, base, canonical)

  assert.equal(merged.revision, 4)
  assert.equal(merged.messages.find(message => message.id === 'shared-user').text, 'locally edited')
  assert.deepEqual(merged.messages.map(message => message.id), ['shared-user', 'remote-assistant'])
})

test('three-way queued merge keeps concurrent additions but honors a local clear', () => {
  const base = payload(2, ['old-user', 'old-assistant'])
  const local = payload(2, [])
  const canonical = payload(3, ['old-user', 'old-assistant', 'concurrent-user'])

  const merged = mergeQueuedWizardConversationSnapshots(local, base, canonical)

  assert.deepEqual(merged.messages.map(message => message.id), ['concurrent-user'])
})

test('three-way queued merge persists an updated execution card by stable id', () => {
  const base = payload(1, ['user'])
  base.executions = [{ id: 'card-1', state: 'running' }]
  const local = clone(base)
  local.executions = [{ id: 'card-1', state: 'completed' }]
  const canonical = clone(base)
  canonical.revision = 2

  const merged = mergeQueuedWizardConversationSnapshots(local, base, canonical)

  assert.deepEqual(merged.executions, [{ id: 'card-1', state: 'completed' }])
})

test('a CAS conflict during a queued edit keeps the edit and the concurrent turn', async () => {
  const base = payload(4, ['shared-user'])
  const snapshots = new Map([['workspace-a', clone(base)]])
  const local = clone(base)
  local.messages[0].text = 'edited after hydration'
  let canonical = payload(5, ['shared-user', 'remote-assistant'])
  canonical.messages[0].text = base.messages[0].text
  let saves = 0
  const transport = {
    async fetch() { return clone(canonical) },
    async save(_workspace, conversation) {
      saves += 1
      if (saves === 1) throw revisionConflict(conversation.revision, canonical.revision)
      assert.equal(conversation.revision, 5)
      canonical = { ...clone(conversation), revision: 6 }
      return clone(canonical)
    },
  }

  const saved = await persistQueuedWizardConversation({
    workspace: 'workspace-a',
    captured: local,
    base,
  }, snapshots, transport)

  assert.equal(saved.merged, true)
  assert.equal(saved.conversation.messages.find(message => message.id === 'shared-user').text, 'edited after hydration')
  assert.deepEqual(saved.conversation.messages.map(message => message.id), ['shared-user', 'remote-assistant'])
})

test('a late hydration fetch cannot replace a newer confirmed snapshot', () => {
  const confirmed = payload(8, ['confirmed-user', 'confirmed-assistant'])
  const staleFetch = payload(7, ['stale-user'])

  assert.equal(newestWizardConversationSnapshot(confirmed, staleFetch), confirmed)
  assert.equal(newestWizardConversationSnapshot(undefined, staleFetch), staleFetch)
  assert.equal(newestWizardConversationSnapshot(staleFetch, confirmed), confirmed)
})
