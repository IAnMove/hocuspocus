import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compareBudget, disabledHits, scanCounts } from './controlA11yScan.ts'

test('a disabled control with no reason is counted', () => {
  assert.equal(disabledHits('fixture.tsx', `export const View = () => <button disabled={busy}>Go</button>`).length, 1)
  assert.equal(disabledHits('fixture.tsx', `export const View = () => <button disabled={busy} title="Wait">Go</button>`).length, 0)
  assert.equal(disabledHits('fixture.tsx', `export const View = () => <button disabled={busy} aria-describedby="why">Go</button>`).length, 0)
  assert.equal(disabledHits('fixture.tsx', `export const View = () => <button disabled={false}>Go</button>`).length, 0)
  assert.equal(disabledHits('fixture.tsx', `export const View = () => <button disabled>Go</button>`).length, 1)
})

test('disabled controls keep a reason', () => {
  const budget = JSON.parse(readFileSync(new URL('./disabledReasonBudget.json', import.meta.url), 'utf8')) as Record<string, number>
  const problems = compareBudget(budget, scanCounts('disabled'), 'disabledReasonBudget.json')
  assert.deepEqual(problems, [], problems.join('\n'))
})
