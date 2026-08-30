import assert from 'node:assert/strict'
import test from 'node:test'

const clone = value => JSON.parse(JSON.stringify(value))

function memoryPersistence() {
  let collection = { version: 1, revision: 0, workflows: [] }
  return {
    async load() { return clone(collection) },
    async save(_workspace, next) {
      if (next.revision !== collection.revision) throw new Error('revision conflict')
      collection = { ...clone(next), revision: collection.revision + 1 }
      return clone(collection)
    },
    snapshot() { return clone(collection) },
  }
}

function taskEvent(eventId, taskId, status, resultRefs = []) {
  return {
    event_id: eventId,
    task_id: taskId,
    root_id: taskId,
    sequence: eventId,
    timestamp: eventId,
    type: `task.${status}`,
    changes: { status, result_refs: resultRefs, message: status },
  }
}

test('a durable workflow waits for a task then advances once on duplicate completion events', async () => {
  const { WizardWorkflowRuntime } = await import('../src/features/agent/wizardWorkflowRuntime.ts')
  const persistence = memoryPersistence()
  let queueCalls = 0
  let finishCalls = 0
  const definition = {
    type: 'mock_media',
    steps: [{
      stepId: 'queue', kind: 'queue media',
      async execute() {
        queueCalls += 1
        return { state: 'queued', taskId: 'task-audio-1' }
      },
    }, {
      stepId: 'finish', kind: 'publish result',
      async execute() {
        finishCalls += 1
        return { state: 'completed', output: { published: true }, outputRefs: ['final.mp4'] }
      },
    }],
  }
  const first = new WizardWorkflowRuntime(persistence)
  first.register(definition)
  await first.open('demo')
  const started = await first.start({
    workflowId: 'workflow-1', type: 'mock_media', workspace: 'demo',
    userRequest: 'Create it', inputSnapshot: { prompt: 'stars' },
    confirmationScope: ['generate', 'publish'],
  })
  assert.equal(started.state, 'queued')
  assert.equal(started.steps[0].state, 'waiting')
  assert.equal(queueCalls, 1)

  // Simulate a full reload. Hydration must not queue the first step again.
  const reloaded = new WizardWorkflowRuntime(persistence)
  reloaded.register(definition)
  const updates = []
  reloaded.subscribe(update => updates.push(update))
  await reloaded.open('demo')
  assert.equal(queueCalls, 1)

  const completion = taskEvent(41, 'task-audio-1', 'completed', ['song.wav'])
  await Promise.all([
    reloaded.handleTaskEvent(completion),
    reloaded.handleTaskEvent(completion),
  ])
  const completed = reloaded.get('workflow-1')
  assert.equal(completed.state, 'completed')
  assert.equal(completed.currentStep, 2)
  assert.equal(finishCalls, 1)
  assert.deepEqual(completed.outputRefs, ['song.wav', 'final.mp4'])
  assert.deepEqual(completed.processedEventIds, [41])

  // Chat updates replace one durable card instead of appending one per event.
  const cardsById = new Map(updates.map(update => [update.card.id, update.card]))
  assert.equal(cardsById.size, 1)
  assert.equal(cardsById.get('workflow-1').state, 'completed')
})

test('workflow failures persist and explicit resume retries only the current step', async () => {
  const { WizardWorkflowRuntime } = await import('../src/features/agent/wizardWorkflowRuntime.ts')
  const persistence = memoryPersistence()
  let calls = 0
  const runtime = new WizardWorkflowRuntime(persistence)
  runtime.register({
    type: 'recoverable',
    steps: [{
      stepId: 'unstable', kind: 'recoverable operation',
      async execute() {
        calls += 1
        if (calls === 1) throw new Error('temporary failure')
        return { state: 'completed', outputRefs: ['recovered.mp4'] }
      },
    }],
  })
  await runtime.open('demo')
  const failed = await runtime.start({
    workflowId: 'workflow-retry', type: 'recoverable', workspace: 'demo', userRequest: 'Retry me',
  })
  assert.equal(failed.state, 'failed')
  assert.equal(failed.recoverableError, 'temporary failure')
  const completed = await runtime.resume('workflow-retry')
  assert.equal(completed.state, 'completed')
  assert.equal(completed.attempts, 1)
  assert.equal(completed.steps[0].attempts, 2)
  assert.equal(calls, 2)
})

test('waiting workflow cancellation is durable and does not run its next step', async () => {
  const { WizardWorkflowRuntime } = await import('../src/features/agent/wizardWorkflowRuntime.ts')
  const persistence = memoryPersistence()
  let nextCalls = 0
  const runtime = new WizardWorkflowRuntime(persistence)
  runtime.register({
    type: 'cancellable',
    steps: [{ stepId: 'wait', kind: 'wait', async execute() { return { state: 'waiting', taskId: 'task-wait' } } },
      { stepId: 'next', kind: 'next', async execute() { nextCalls += 1; return { state: 'completed' } } }],
  })
  await runtime.open('demo')
  await runtime.start({ workflowId: 'workflow-cancel', type: 'cancellable', workspace: 'demo', userRequest: 'Stop later' })
  const cancelled = await runtime.cancel('workflow-cancel')
  assert.equal(cancelled.state, 'cancelled')
  assert.equal(cancelled.cancelRequested, true)
  await runtime.handleTaskEvent(taskEvent(9, 'task-wait', 'completed'))
  assert.equal(runtime.get('workflow-cancel').state, 'cancelled')
  assert.equal(nextCalls, 0)
})
