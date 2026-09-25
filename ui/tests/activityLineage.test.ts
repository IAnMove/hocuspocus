import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyCanonicalTaskEvent,
  reconcileCanonicalTaskSnapshot,
} from '../src/lib/canonicalTaskEvents.ts'
import {
  activityRequestKey,
  findActivityGroup,
  groupActivityTasks,
  preserveActivityChrome,
  taskIntentId,
  taskReadingState,
  type ActivityTaskLike,
} from '../src/features/activity/lineage.ts'

function task(overrides: Partial<ActivityTaskLike> & Pick<ActivityTaskLike, 'id'>): ActivityTaskLike {
  const status = overrides.status || 'queued'
  return {
    root_id: overrides.root_id || overrides.id,
    parent_id: null,
    kind: 'generation',
    title: overrides.title || overrides.id,
    workflow: 'generation',
    status,
    phase: overrides.phase || status,
    message: overrides.message || status,
    created_at: 10,
    updated_at: 10,
    attempt: 1,
    max_attempts: 3,
    ...overrides,
  }
}

test('groups child jobs under the original request intent and keeps a stable created order', () => {
  const parent = task({
    id: 'task-root',
    title: 'Story request',
    status: 'running',
    created_at: 20,
    metadata: { intent_id: 'intent-story', receipt_id: 'intent-story' },
  })
  const olderChild = task({
    id: 'task-song',
    root_id: 'task-root',
    parent_id: 'task-root',
    title: 'Song',
    status: 'completed',
    created_at: 21,
    result_refs: ['song.wav'],
    metadata: { intent_id: 'intent-story' },
  })
  const newerChild = task({
    id: 'task-video',
    root_id: 'task-root',
    parent_id: 'task-root',
    title: 'Video',
    status: 'running',
    created_at: 22,
    metadata: { intent_id: 'intent-story' },
  })
  const other = task({
    id: 'task-other',
    title: 'Later image',
    status: 'queued',
    created_at: 40,
    metadata: { intent_id: 'intent-image' },
  })
  const grouped = groupActivityTasks([newerChild, other, olderChild, parent])
  assert.deepEqual(grouped.map(group => group.id), ['intent:intent-image', 'intent:intent-story'])
  assert.equal(grouped[1].jobs.map(job => job.id).join(','), 'task-song,task-video')
  assert.equal(grouped[1].receiptId, 'intent-story')
  assert.equal(grouped[1].readingState, 'running')
  const progressed = groupActivityTasks([
    { ...parent, progress: 0.9, current: 9, total: 10, updated_at: 99 },
    { ...olderChild, updated_at: 99 },
    { ...newerChild, progress: 0.4, updated_at: 99 },
    { ...other, updated_at: 99 },
  ])
  assert.deepEqual(progressed.map(group => group.id), grouped.map(group => group.id))
})

test('duplicate and out-of-order SSE events do not duplicate groups or change chrome', () => {
  const created = {
    event_id: 1,
    task_id: 'task-root',
    root_id: 'task-root',
    sequence: 1,
    timestamp: 20,
    type: 'task.created',
    changes: {
      id: 'task-root',
      root_id: 'task-root',
      status: 'queued',
      updated_at: 20,
      created_at: 20,
      title: 'Queued image',
      kind: 'generation',
      workflow: 'generation',
      metadata: { intent_id: 'intent-a', commandId: 'intent-a' },
      resumable: false,
    },
  }
  let tasks: ActivityTaskLike[] = []
  tasks = applyCanonicalTaskEvent(tasks, created).tasks as ActivityTaskLike[]
  tasks = applyCanonicalTaskEvent(tasks, created).tasks as ActivityTaskLike[]
  const duplicateProgress = {
    ...created,
    event_id: 2,
    timestamp: 21,
    type: 'task.progress',
    changes: { status: 'running', updated_at: 21, progress: 0.2, current: 2, total: 10 },
  }
  tasks = applyCanonicalTaskEvent(tasks, duplicateProgress).tasks as ActivityTaskLike[]
  tasks = applyCanonicalTaskEvent(tasks, duplicateProgress).tasks as ActivityTaskLike[]
  const stale = {
    ...created,
    event_id: 3,
    timestamp: 10,
    type: 'task.progress',
    changes: { status: 'queued', updated_at: 10, progress: 0 },
  }
  const ignored = applyCanonicalTaskEvent(tasks, stale)
  assert.equal(ignored.tasks, tasks)
  const groups = groupActivityTasks(tasks)
  assert.equal(groups.length, 1)
  assert.equal(groups[0].id, 'intent:intent-a')
  assert.equal(groups[0].readingState, 'running')
  const chrome = preserveActivityChrome({
    selectedId: groups[0].id,
    expandedIds: [groups[0].id],
    inspectedAttemptByGroup: { [groups[0].id]: 'prev' },
  })
  const afterMoreProgress = groupActivityTasks(applyCanonicalTaskEvent(tasks, {
    ...duplicateProgress,
    event_id: 4,
    timestamp: 40,
    changes: { status: 'running', updated_at: 40, progress: 0.8, current: 8, total: 10 },
  }).tasks as ActivityTaskLike[])
  assert.deepEqual(afterMoreProgress.map(group => group.id), [groups[0].id])
  assert.equal(chrome.selectedId, afterMoreProgress[0].id)
  assert.deepEqual(chrome.expandedIds, [afterMoreProgress[0].id])
})

test('polling reconcile keeps group identity after an in-flight SSE patch', () => {
  const current = [task({
    id: 'task-root',
    status: 'running',
    updated_at: 50,
    progress: 0.7,
    metadata: { intent_id: 'intent-poll' },
  })]
  const snapshot = [task({
    id: 'task-root',
    status: 'running',
    updated_at: 40,
    progress: 0.2,
    metadata: { intent_id: 'intent-poll' },
  })]
  const merged = reconcileCanonicalTaskSnapshot(current, snapshot, 40)
  const groups = groupActivityTasks(merged)
  assert.equal(groups.length, 1)
  assert.equal(groups[0].id, 'intent:intent-poll')
  assert.equal(groups[0].primary.updated_at, 50)
})

test('workspace isolation does not mix tasks from another folder', () => {
  const local = task({
    id: 'task-a',
    created_at: 30,
    metadata: { intent_id: 'intent-a', workspace: 'alpha' },
  })
  const foreign = task({
    id: 'task-b',
    created_at: 40,
    metadata: { intent_id: 'intent-b', workspace: 'beta' },
  })
  const grouped = groupActivityTasks([local, foreign], { workspace: 'alpha' })
  assert.deepEqual(grouped.map(group => group.primary.id), ['task-a'])
})

test('an admitted generation without an artifact is not completed', () => {
  const admitted = task({
    id: 'task-admitted',
    status: 'queued',
    backend_job_id: 'job-1',
    metadata: { intent_id: 'intent-admit', receipt: { commandId: 'intent-admit' } },
  })
  const fakeComplete = task({
    id: 'task-empty',
    status: 'completed',
    kind: 'generation',
    workflow: 'generation',
    result_refs: [],
    metadata: { intent_id: 'intent-empty' },
  })
  const prepared = task({
    id: 'task-client-prep',
    status: 'created',
    metadata: {},
  })
  assert.equal(taskReadingState(admitted), 'admitted')
  assert.equal(taskReadingState(fakeComplete), 'partial')
  assert.equal(taskReadingState(prepared), 'prepared')
  assert.equal(groupActivityTasks([admitted])[0].readingState, 'admitted')
  assert.equal(groupActivityTasks([fakeComplete])[0].readingState, 'partial')
  assert.notEqual(groupActivityTasks([admitted])[0].readingState, 'completed')
})

test('retry of a failed task keeps the original receipt and previous attempt', () => {
  const failed = task({
    id: 'task-retry',
    status: 'failed',
    attempt: 1,
    created_at: 10,
    error: { message: 'Provider stopped', retryable: true },
    metadata: {
      intent_id: 'intent-retry',
      receipt_id: 'intent-retry',
      previous_attempts: [{ attempt: 1, status: 'failed', error: 'Provider stopped', created_at: 10 }],
    },
  })
  const retried = task({
    id: 'task-retry',
    status: 'running',
    attempt: 2,
    created_at: 10,
    updated_at: 30,
    metadata: {
      intent_id: 'intent-retry',
      receipt_id: 'intent-retry',
      previous_attempts: [{ attempt: 1, status: 'failed', error: 'Provider stopped', created_at: 10 }],
    },
  })
  const before = groupActivityTasks([failed])
  const after = groupActivityTasks([retried])
  assert.equal(before[0].id, after[0].id)
  assert.equal(after[0].receiptId, 'intent-retry')
  assert.equal(taskIntentId(after[0].primary), 'intent-retry')
  assert.equal(after[0].previousAttempt?.attempt, 1)
  assert.equal(after[0].previousAttempt?.error, 'Provider stopped')
  const found = findActivityGroup(after, { taskId: 'task-retry', intentId: 'intent-retry' })
  assert.equal(found?.receiptId, 'intent-retry')
})

test('request keys consume existing intent, parent and root ids', () => {
  const byId = new Map<string, ActivityTaskLike>()
  const root = task({ id: 'root', metadata: { command_id: 'cmd-1' } })
  const child = task({ id: 'child', root_id: 'root', parent_id: 'root' })
  byId.set(root.id, root)
  byId.set(child.id, child)
  assert.equal(activityRequestKey(child, byId), 'intent:cmd-1')
  assert.equal(activityRequestKey(task({ id: 'solo' }), new Map()), 'root:solo')
})
