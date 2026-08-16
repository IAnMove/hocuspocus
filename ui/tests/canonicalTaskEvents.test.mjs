import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyCanonicalTaskEvent,
  canResumeCanonicalTask,
  canonicalTaskEventUrl,
  canonicalTaskVisualState,
  openCanonicalTaskEventStream,
  reconcileCanonicalTaskSnapshot,
} from '../src/lib/canonicalTaskEvents.ts'

function event(overrides = {}) {
  return {
    event_id: 1,
    task_id: 'task-1',
    root_id: 'task-1',
    sequence: 1,
    timestamp: 101,
    type: 'task.updated',
    changes: { status: 'running', updated_at: 100 },
    context: {},
    ...overrides,
  }
}

test('applies current SSE patches directly and ignores historical replay', () => {
  const tasks = [{ id: 'task-1', status: 'running', updated_at: 100, resumable: false }]

  const historical = applyCanonicalTaskEvent(tasks, event({
    timestamp: 90,
    changes: { status: 'queued', updated_at: 89 },
  }))
  assert.equal(historical.tasks, tasks)

  const current = applyCanonicalTaskEvent(tasks, event({
    timestamp: 102,
    changes: { status: 'completed', updated_at: 101 },
  }))
  assert.notEqual(current.tasks, tasks)
  assert.equal(current.tasks[0].status, 'completed')
  assert.equal(current.needsRefresh, false)
})

test('adds recent creates, ignores unknown history, and requests recovery for a missed create', () => {
  const tasks = [{ id: 'task-1', status: 'completed', updated_at: 200, resumable: false }]
  const oldUnknown = applyCanonicalTaskEvent(tasks, event({
    task_id: 'task-old',
    timestamp: 190,
  }), 200)
  assert.equal(oldUnknown.tasks, tasks)
  assert.equal(oldUnknown.needsRefresh, false)

  const created = applyCanonicalTaskEvent(tasks, event({
    event_id: 2,
    task_id: 'task-2',
    root_id: 'task-2',
    timestamp: 201,
    type: 'task.created',
    changes: { id: 'task-2', status: 'queued', updated_at: 201, resumable: false },
  }), 200)
  assert.equal(created.tasks.length, 2)
  assert.equal(created.tasks[1].id, 'task-2')

  const missedCreate = applyCanonicalTaskEvent(tasks, event({
    event_id: 3,
    task_id: 'task-3',
    timestamp: 202,
  }), 200)
  assert.equal(missedCreate.tasks, tasks)
  assert.equal(missedCreate.needsRefresh, true)
})

test('removes dismissed tasks and never offers Resume for completed work', () => {
  const tasks = [
    { id: 'task-1', status: 'completed', updated_at: 100, resumable: true },
    { id: 'task-2', status: 'cancelled', updated_at: 100, resumable: true },
  ]
  const removed = applyCanonicalTaskEvent(tasks, event({
    task_id: 'task-1',
    type: 'task.dismissed',
    changes: {},
  }))
  assert.deepEqual(removed.tasks.map(task => task.id), ['task-2'])
  assert.equal(canResumeCanonicalTask(tasks[0]), false)
  assert.equal(canResumeCanonicalTask(tasks[1]), true)
  assert.equal(canonicalTaskVisualState('cancelled'), 'cancelled')
  assert.notEqual(canonicalTaskVisualState('cancelled'), 'error')
})

test('full reconciliation preserves an event that arrived during the request', () => {
  const current = [
    { id: 'task-1', status: 'running', updated_at: 105, resumable: false },
    { id: 'task-2', status: 'queued', updated_at: 106, resumable: false },
  ]
  const snapshot = [
    { id: 'task-1', status: 'queued', updated_at: 100, resumable: false },
  ]
  assert.deepEqual(reconcileCanonicalTaskSnapshot(current, snapshot, 100), current)
})

test('reconnects with the last SSE event id instead of replaying from zero', () => {
  const sources = []
  const states = []
  const received = []
  const scheduled = []

  class FakeEventSource {
    constructor(url) {
      this.url = url
      this.onopen = null
      this.onerror = null
      this.listeners = new Map()
      this.closed = false
      sources.push(this)
    }

    addEventListener(type, listener) {
      this.listeners.set(type, listener)
    }

    close() {
      this.closed = true
    }

    emit(payload, lastEventId) {
      this.listeners.get('task')?.({ data: JSON.stringify(payload), lastEventId })
    }
  }

  const close = openCanonicalTaskEventStream(
    '',
    'series workspace',
    value => received.push(value),
    undefined,
    state => states.push(state),
    {
      eventSourceFactory: url => new FakeEventSource(url),
      scheduleRetry: (callback, delayMs) => {
        scheduled.push({ callback, delayMs })
        return scheduled.length
      },
      cancelRetry: () => undefined,
    },
  )

  assert.equal(sources[0].url, '/api/v1/tasks/events?workspace=series+workspace')
  sources[0].onopen?.({})
  sources[0].emit(event({ event_id: 41 }), '41')
  sources[0].emit(event({ event_id: 41 }), '41')
  assert.equal(received.length, 1)

  sources[0].onerror?.({})
  assert.equal(sources[0].closed, true)
  assert.equal(scheduled[0].delayMs, 1000)
  scheduled[0].callback()

  assert.equal(sources[1].url, '/api/v1/tasks/events?workspace=series+workspace&after=41')
  assert.deepEqual(states.slice(0, 4), ['connecting', 'open', 'retrying', 'connecting'])
  close()
  assert.equal(sources[1].closed, true)
  assert.equal(states.at(-1), 'closed')
})

test('builds a replay URL only when a cursor exists', () => {
  assert.equal(canonicalTaskEventUrl('', 'default'), '/api/v1/tasks/events?workspace=default')
  assert.equal(canonicalTaskEventUrl('', 'default', 12), '/api/v1/tasks/events?workspace=default&after=12')
})

test('starts after a 10,000-event snapshot and still receives the concurrent change', () => {
  const sources = []
  const received = []
  const scheduled = []

  class FakeEventSource {
    constructor(url) {
      this.url = url
      this.onopen = null
      this.onerror = null
      this.listeners = new Map()
      sources.push(this)
    }

    addEventListener(type, listener) {
      this.listeners.set(type, listener)
    }

    close() {}

    emit(payload, lastEventId) {
      this.listeners.get('task')?.({ data: JSON.stringify(payload), lastEventId })
    }
  }

  const close = openCanonicalTaskEventStream('', 'default', value => received.push(value), undefined, undefined, {
    initialEventId: 10_000,
    eventSourceFactory: url => new FakeEventSource(url),
    scheduleRetry: callback => {
      scheduled.push(callback)
      return scheduled.length
    },
  })

  assert.equal(sources[0].url, '/api/v1/tasks/events?workspace=default&after=10000')
  sources[0].emit(event({ event_id: 9_999 }), '9999')
  sources[0].emit(event({ event_id: 10_001, timestamp: 201 }), '10001')
  assert.deepEqual(received.map(item => item.event_id), [10_001])

  sources[0].onerror?.({})
  scheduled[0]()
  assert.equal(sources[1].url, '/api/v1/tasks/events?workspace=default&after=10001')
  close()
})
