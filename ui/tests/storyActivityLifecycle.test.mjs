import assert from 'node:assert/strict'
import test from 'node:test'

import { createStoryActivityLifecycle } from '../src/features/stories/activityLifecycle.ts'
import { createKeyedWriteSequencer } from '../src/lib/keyedWriteSequencer.ts'

function activityHarness() {
  const writes = []
  const dismissals = []
  const activity = createStoryActivityLifecycle({
    id: 'story-lab:project:test',
    title: 'Story Lab test',
    phase: 'planning',
    message: 'Starting',
    total: 2,
    publish: value => writes.push(structuredClone(value)),
    scheduleDismiss: id => dismissals.push({ id, statusAtSchedule: writes.at(-1)?.status }),
  })
  return { activity, writes, dismissals }
}

test('successful Story activity becomes terminal before dismissal', () => {
  const { activity, writes, dismissals } = activityHarness()
  activity.update('Halfway', 'planning', 1, 2)
  activity.finish('Ready')
  activity.update('Late poll', 'planning', 2, 2)

  assert.deepEqual(writes.map(item => item.status), ['running', 'running', 'completed'])
  assert.equal(writes.at(-1).message, 'Ready')
  assert.deepEqual(dismissals, [{ id: activity.id, statusAtSchedule: 'completed' }])
})

test('Story activity error is terminal and is retained for inspection', () => {
  const { activity, writes, dismissals } = activityHarness()
  activity.fail(new Error('Planner failed'), 'planning')
  activity.finish('Incorrect late success')

  assert.equal(writes.at(-1).status, 'failed')
  assert.equal(writes.at(-1).error, 'Planner failed')
  assert.deepEqual(dismissals, [])
})

test('Story activity cancellation is terminal before dismissal', () => {
  const { activity, writes, dismissals } = activityHarness()
  activity.cancel('Cancellation requested')
  activity.finish('Incorrect late success')

  assert.equal(writes.at(-1).status, 'cancelled')
  assert.equal(writes.at(-1).phase, 'cancelled')
  assert.deepEqual(dismissals, [{ id: activity.id, statusAtSchedule: 'cancelled' }])
})

test('backend handoff survives refresh as terminal and ignores late callbacks', () => {
  const { activity, writes, dismissals } = activityHarness()
  activity.handoff('Continuing as recoverable job story-123')
  const refreshedSnapshot = JSON.parse(JSON.stringify(writes.at(-1)))
  activity.fail(new Error('Backend owns this failure now'))
  activity.cancel('Backend owns this cancellation now')

  assert.equal(refreshedSnapshot.status, 'completed')
  assert.equal(refreshedSnapshot.phase, 'handed_off')
  assert.equal(writes.length, 2)
  assert.deepEqual(dismissals, [{ id: activity.id, statusAtSchedule: 'completed' }])
})

test('canonical running, terminal and DELETE writes stay ordered per root', async () => {
  const sequencer = createKeyedWriteSequencer()
  const order = []
  let releaseRunning
  const runningGate = new Promise(resolve => { releaseRunning = resolve })

  const running = sequencer.enqueue('client-root', async () => {
    await runningGate
    order.push('running')
  })
  const terminal = sequencer.enqueue('client-root', async () => { order.push('completed') })
  const dismiss = sequencer.enqueue('client-root', async () => { order.push('delete') })

  await Promise.resolve()
  assert.deepEqual(order, [])
  assert.equal(sequencer.hasPending('client-root'), true)
  releaseRunning()
  await Promise.all([running, terminal, dismiss])

  assert.deepEqual(order, ['running', 'completed', 'delete'])
  assert.equal(sequencer.hasPending('client-root'), false)
})
