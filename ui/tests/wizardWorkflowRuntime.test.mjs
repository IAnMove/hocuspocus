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

test('awaiting input persists the question, validates answers, and resumes the same step once', async () => {
  const { WizardWorkflowRuntime } = await import('../src/features/agent/wizardWorkflowRuntime.ts')
  const persistence = memoryPersistence()
  const calls = []
  const definition = {
    type: 'needs_choice',
    steps: [{
      stepId: 'choose-audio', kind: 'choose audio',
      async execute(context) {
        calls.push({
          input: clone(context.step.input),
          snapshot: clone(context.inputSnapshot),
        })
        if (calls.length === 1) {
          return {
            state: 'awaiting_input',
            awaitingInput: {
              reason: 'Elige el audio canónico para continuar.',
              fields: ['audio.outputName'],
              options: [
                { value: 'himno-v2.wav', label: 'El Himno v2', field: 'audio.outputName' },
                { value: 'himno-v1.wav', label: 'El Himno v1', field: 'audio.outputName' },
              ],
              recommended: 'himno-v2.wav',
              resolvedEntityIds: { storyId: 'story-42' },
            },
          }
        }
        return {
          state: 'completed',
          output: { selectedAudio: context.step.input.audio.outputName },
          outputRefs: [context.step.input.audio.outputName],
        }
      },
    }],
  }
  const runtime = new WizardWorkflowRuntime(persistence)
  runtime.register(definition)
  await runtime.open('demo')
  const started = await runtime.start({
    workflowId: 'workflow-question', type: 'needs_choice', workspace: 'demo',
    userRequest: 'Usa la canción correcta',
    inputSnapshot: {
      prompt: 'videoclip', audio: { outputName: 'unknown.wav' }, untouched: 'keep-me',
    },
    stepInputs: {
      'choose-audio': { audio: { outputName: 'unknown.wav' }, untouched: 'keep-step' },
    },
  })

  assert.equal(started.state, 'awaiting_input')
  assert.equal(started.steps[0].state, 'awaiting_input')
  assert.deepEqual(started.pendingInput.fields, ['audio.outputName'])
  assert.equal(started.pendingInput.options[0].value, 'himno-v2.wav')
  assert.equal(started.pendingInput.recommended, 'himno-v2.wav')
  assert.deepEqual(started.pendingInput.resolvedEntityIds, { storyId: 'story-42' })
  assert.equal(persistence.snapshot().workflows[0].pendingInput.reason, 'Elige el audio canónico para continuar.')

  // A reload must show the exact same durable question instead of executing it
  // again or silently losing the selected entity identity.
  const reloaded = new WizardWorkflowRuntime(persistence)
  reloaded.register(definition)
  await reloaded.open('demo')
  const restored = reloaded.get('workflow-question')
  assert.equal(restored.state, 'awaiting_input')
  assert.equal(restored.pendingInput.version, 1)
  assert.deepEqual(restored.pendingInput.fields, ['audio.outputName'])
  assert.deepEqual(restored.resolvedEntityIds, { storyId: 'story-42' })
  assert.equal(calls.length, 1)

  await assert.rejects(
    () => reloaded.answer('workflow-question', {
      'audio.outputName': 'himno-v2.wav', unexpected: true,
    }, { version: 1 }),
    /undeclared field/,
  )
  await assert.rejects(
    () => reloaded.answer('workflow-question', {}, { version: 1 }),
    /missing field/,
  )
  await assert.rejects(
    () => reloaded.answer('workflow-question', { 'audio.outputName': 'other.wav' }, { version: 1 }),
    /available options/,
  )
  await assert.rejects(
    () => reloaded.answer('workflow-question', { 'audio.outputName': 'himno-v1.wav' }, { version: 2 }),
    /stale/,
  )
  assert.equal(reloaded.get('workflow-question').state, 'awaiting_input')
  assert.equal(calls.length, 1)

  const completed = await reloaded.answer(
    'workflow-question',
    { 'audio.outputName': 'himno-v2.wav' },
    { version: 1, stepId: 'choose-audio' },
  )
  assert.equal(completed.state, 'completed')
  assert.equal(completed.currentStep, 1)
  assert.equal(calls.length, 2)
  assert.deepEqual(calls[1].input, {
    audio: { outputName: 'himno-v2.wav' }, untouched: 'keep-step',
  })
  assert.deepEqual(calls[1].snapshot, {
    prompt: 'videoclip', audio: { outputName: 'himno-v2.wav' }, untouched: 'keep-me',
  })
  assert.deepEqual(completed.outputRefs, ['himno-v2.wav'])
  assert.deepEqual(completed.pendingInput.answer, { 'audio.outputName': 'himno-v2.wav' })
  assert.ok(completed.pendingInput.answeredAt > 0)

  // Replaying the same UI event after the checkpoint has been consumed is a
  // no-op: it cannot overwrite the answer or execute the step a third time.
  const duplicate = await reloaded.answer(
    'workflow-question',
    { 'audio.outputName': 'himno-v1.wav' },
    { version: 1, stepId: 'choose-audio' },
  )
  assert.equal(duplicate.state, 'completed')
  assert.equal(calls.length, 2)
  assert.deepEqual(duplicate.pendingInput.answer, { 'audio.outputName': 'himno-v2.wav' })
})

test('awaiting input rejects prototype-polluting field paths before persistence', async () => {
  const { WizardWorkflowRuntime } = await import('../src/features/agent/wizardWorkflowRuntime.ts')
  const persistence = memoryPersistence()
  const runtime = new WizardWorkflowRuntime(persistence)
  runtime.register({
    type: 'unsafe_question',
    steps: [{
      stepId: 'unsafe', kind: 'unsafe question',
      async execute() {
        return {
          state: 'awaiting_input',
          awaitingInput: {
            reason: 'bad field', fields: ['__proto__.polluted'],
          },
        }
      },
    }],
  })
  await runtime.open('demo')
  const failed = await runtime.start({
    workflowId: 'workflow-unsafe', type: 'unsafe_question', workspace: 'demo', userRequest: 'test',
  })
  assert.equal(failed.state, 'failed')
  assert.match(failed.recoverableError, /requested input/)
  assert.equal(Object.prototype.polluted, undefined)
})
