import assert from 'node:assert/strict'
import test from 'node:test'

import { createActivityPublicationGate } from '../src/lib/activityPublication.ts'


function fakeClock() {
  let current = 0
  const timers = []
  return {
    now: () => current,
    advanceTo: value => { current = value },
    schedule: (callback, delay) => {
      const timer = { callback, delay, cancelled: false }
      timers.push(timer)
      return timer
    },
    cancel: timer => { timer.cancelled = true },
    flush: () => {
      for (const timer of timers.splice(0)) {
        if (!timer.cancelled) timer.callback()
      }
    },
  }
}


test('100 identical progress polls publish only the first semantic state', () => {
  const clock = fakeClock()
  const gate = createActivityPublicationGate(1500, clock.now, clock.schedule, clock.cancel)
  const published = []
  for (let index = 0; index < 100; index += 1) {
    clock.advanceTo(index * 100)
    gate.publish({
      id: 'plan-1', status: 'running', phase: 'planning', current: 1, total: 10,
      updatedAt: index * 100,
    }, value => published.push(value))
  }
  clock.flush()
  assert.equal(published.length, 1)
})


test('changing non-terminal progress is throttled and coalesced to the newest value', () => {
  const clock = fakeClock()
  const gate = createActivityPublicationGate(1500, clock.now, clock.schedule, clock.cancel)
  const published = []
  gate.publish({ id: 'plan-2', status: 'running', current: 0 }, value => published.push(value))
  for (let current = 1; current <= 100; current += 1) {
    clock.advanceTo(100)
    gate.publish({ id: 'plan-2', status: 'running', current }, value => published.push(value))
  }
  clock.advanceTo(1500)
  clock.flush()
  assert.deepEqual(published.map(value => value.current), [0, 100])
})


test('terminal and error states publish immediately and cancel stale progress', () => {
  for (const status of ['completed', 'failed']) {
    const clock = fakeClock()
    const gate = createActivityPublicationGate(1500, clock.now, clock.schedule, clock.cancel)
    const published = []
    gate.publish({ id: status, status: 'running', current: 0 }, value => published.push(value))
    clock.advanceTo(100)
    gate.publish({ id: status, status: 'running', current: 1 }, value => published.push(value))
    clock.advanceTo(200)
    gate.publish({ id: status, status, current: 1 }, value => published.push(value))
    clock.advanceTo(1500)
    clock.flush()
    assert.deepEqual(published.map(value => value.status), ['running', status])
  }
})
