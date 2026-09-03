import assert from 'node:assert/strict'
import test from 'node:test'

const {
  saveWizardConversationWithRecovery,
  mergeWizardConversationSnapshots,
  mergeQueuedWizardConversationSnapshots,
  enqueueWizardConversationSave,
  persistQueuedWizardConversation,
  rebaseStaleWizardConversationHydration,
  resolveWizardConversationHydration,
} = await import('../src/features/agent/wizardConversationPersistence.ts')
const {
  WizardConversationRequestError,
  fetchWizardConversation,
} = await import('../src/api/wizard.ts')
const {
  isWizardConversationWriteCurrent,
  hasExclusiveWizardMessages,
  mergeWizardMessages,
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

test('a queued clear uses its recorded ancestor after a predecessor advances the snapshot', async () => {
  const clearBase = payload(1, ['cleared-user', 'cleared-assistant'])
  const canonical = payload(2, ['cleared-user', 'cleared-assistant', 'concurrent-user'])
  const capturedClear = payload(1, ['welcome-after-clear'])
  const snapshots = new Map([['workspace-a', clone(canonical)]])
  const transport = {
    async fetch() { return clone(canonical) },
    async save(_workspace, conversation) {
      assert.equal(conversation.revision, 2)
      assert.deepEqual(conversation.messages.map(message => message.id), [
        'concurrent-user',
        'welcome-after-clear',
      ])
      return { ...clone(conversation), revision: 3 }
    },
  }

  const saved = await persistQueuedWizardConversation({
    workspace: 'workspace-a',
    captured: capturedClear,
    base: clearBase,
    honorLocalDeletes: true,
  }, snapshots, transport)

  assert.equal(saved.conversation.revision, 3)
  assert.deepEqual(snapshots.get('workspace-a'), saved.conversation)
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

test('a normal queued save cannot delete canonical turns outside the 40-message UI window', async () => {
  const ids = Array.from({ length: 50 }, (_value, index) => `message-${index + 1}`)
  const canonical = payload(7, ids)
  const visibleWindow = payload(7, [...ids.slice(-40), 'new-local-message'])
  const snapshots = new Map([['workspace-a', clone(canonical)]])
  const transport = {
    async fetch() { return clone(canonical) },
    async save(_workspace, conversation) {
      assert.equal(conversation.revision, 7)
      assert.deepEqual(conversation.messages.map(message => message.id), [...ids, 'new-local-message'])
      return { ...clone(conversation), revision: 8 }
    },
  }

  await persistQueuedWizardConversation({
    workspace: 'workspace-a',
    captured: visibleWindow,
    base: canonical,
  }, snapshots, transport)
})

test('a conflict retry keeps using the recorded clear ancestor', async () => {
  const clearBase = payload(1, ['cleared-user', 'cleared-assistant'])
  const capturedClear = payload(1, ['welcome-after-clear'])
  const snapshotAfterEarlierWrite = payload(2, ['concurrent-before-conflict'])
  const remoteAfterConflict = payload(3, [
    'cleared-user',
    'cleared-assistant',
    'concurrent-before-conflict',
    'concurrent-during-conflict',
  ])
  const snapshots = new Map([['workspace-a', clone(snapshotAfterEarlierWrite)]])
  let saves = 0
  const transport = {
    async fetch() { return clone(remoteAfterConflict) },
    async save(_workspace, conversation) {
      saves += 1
      if (saves === 1) throw revisionConflict(conversation.revision, remoteAfterConflict.revision)
      assert.equal(conversation.revision, 3)
      assert.deepEqual(conversation.messages.map(message => message.id), [
        'concurrent-before-conflict',
        'concurrent-during-conflict',
        'welcome-after-clear',
      ])
      return { ...clone(conversation), revision: 4 }
    },
  }

  const saved = await persistQueuedWizardConversation({
    workspace: 'workspace-a',
    captured: capturedClear,
    base: clearBase,
    honorLocalDeletes: true,
  }, snapshots, transport)

  assert.equal(saved.merged, true)
  assert.equal(saved.conversation.revision, 4)
})

test('a shared message id retains the newer local workflow card', () => {
  const remote = [{
    id: 'assistant-workflow', role: 'assistant', text: 'Generating', createdAt: 1,
    cards: [{ id: 'card-1', state: 'running' }],
  }]
  const local = [{
    ...remote[0],
    text: 'Completed',
    cards: [{ id: 'card-1', state: 'completed' }],
  }]

  const merged = mergeWizardMessages(local, remote)

  assert.equal(merged[0].text, 'Completed')
  assert.equal(merged[0].cards[0].state, 'completed')
})

test('a late hydration fetch cannot replace a newer confirmed snapshot or visible edits', () => {
  const confirmed = payload(8, ['confirmed-user', 'confirmed-assistant'])
  const staleFetch = payload(7, ['stale-user'])

  assert.deepEqual(resolveWizardConversationHydration(confirmed, staleFetch), {
    snapshot: confirmed,
    applyToVisibleState: false,
  })
  assert.deepEqual(resolveWizardConversationHydration(confirmed, clone(confirmed)), {
    snapshot: confirmed,
    applyToVisibleState: false,
  })
  assert.deepEqual(resolveWizardConversationHydration(undefined, staleFetch), {
    snapshot: staleFetch,
    applyToVisibleState: true,
  })
  assert.deepEqual(resolveWizardConversationHydration(staleFetch, confirmed), {
    snapshot: confirmed,
    applyToVisibleState: true,
  })
})

test('stale hydration rebases visible edits without dropping confirmed turns', () => {
  const stale = payload(7, ['shared-user'])
  const confirmed = payload(8, ['shared-user', 'confirmed-assistant'])
  const visible = clone(stale)
  visible.messages[0].text = 'edited while hydration was in flight'

  const rebased = rebaseStaleWizardConversationHydration(visible, stale, confirmed)

  assert.equal(rebased.needsPersist, true)
  assert.equal(rebased.conversation.revision, 8)
  assert.equal(rebased.conversation.messages[0].text, 'edited while hydration was in flight')
  assert.deepEqual(rebased.conversation.messages.map(message => message.id), [
    'shared-user',
    'confirmed-assistant',
  ])
})

test('stale hydration restores confirmed-only turns without scheduling a redundant save', () => {
  const stale = payload(7, ['shared-user'])
  const confirmed = payload(8, ['shared-user', 'confirmed-assistant'])

  const rebased = rebaseStaleWizardConversationHydration(clone(stale), stale, confirmed)

  assert.equal(rebased.needsPersist, false)
  assert.deepEqual(rebased.conversation.messages, confirmed.messages)
})

test('UI and server message shape differences are not treated as local edits', () => {
  const serverMessage = (id, role, text, createdAt, extra = {}) => ({
    id,
    role,
    text,
    createdAt,
    cards: [],
    executionKey: '',
    jobLinks: [],
    lastState: '',
    error: '',
    ...extra,
  })
  const stale = {
    version: 1,
    revision: 7,
    messages: [serverMessage('shared-user', 'user', 'hello', 1)],
    executions: [],
  }
  const confirmed = {
    version: 1,
    revision: 8,
    messages: [
      serverMessage('shared-user', 'user', 'hello', 1, { executionKey: 'server-key' }),
      serverMessage('confirmed-assistant', 'assistant', 'reply', 2),
    ],
    executions: [],
  }
  const visible = {
    version: 1,
    revision: 7,
    messages: [{ id: 'shared-user', role: 'user', text: 'hello', createdAt: 1 }],
    executions: [],
  }

  const rebased = rebaseStaleWizardConversationHydration(visible, stale, confirmed)

  assert.equal(rebased.needsPersist, false)
  assert.equal(rebased.conversation.messages[0].executionKey, 'server-key')
  assert.deepEqual(rebased.conversation.messages.map(message => message.id), [
    'shared-user',
    'confirmed-assistant',
  ])
})

test('stale browser cache omissions do not delete newer canonical turns during hydration', () => {
  const stale = payload(7, ['shared-user', 'stale-assistant'])
  const confirmed = payload(8, ['shared-user', 'stale-assistant', 'confirmed-user'])
  const olderVisibleCache = payload(5, ['shared-user'])

  const rebased = rebaseStaleWizardConversationHydration(olderVisibleCache, stale, confirmed)

  assert.equal(rebased.needsPersist, false)
  assert.deepEqual(rebased.conversation.messages, confirmed.messages)
})

test('explicit clear deletes base turns while retaining concurrent canonical additions', () => {
  const stale = payload(7, ['old-user', 'old-assistant'])
  const confirmed = payload(8, ['old-user', 'old-assistant', 'concurrent-user'])
  const cleared = payload(7, ['welcome-after-clear'])

  const rebased = rebaseStaleWizardConversationHydration(cleared, stale, confirmed, {
    honorLocalDeletes: true,
  })

  assert.equal(rebased.needsPersist, true)
  assert.deepEqual(rebased.conversation.messages.map(message => message.id), [
    'concurrent-user',
    'welcome-after-clear',
  ])
})
