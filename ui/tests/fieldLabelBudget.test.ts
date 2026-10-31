import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compareBudget, fieldHits, scanFieldCounts } from './controlA11yScan.ts'

test('a field with no label, id link or accessible name is counted', () => {
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <input />').length, 1)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <textarea />').length, 1)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <select><option /></select>').length, 1)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <label>Name<input /></label>').length, 0)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <><label htmlFor="name">Name</label><input id="name" /></>').length, 0)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <input aria-label="Name" />').length, 0)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <input aria-labelledby="name" />').length, 0)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <input type="hidden" />').length, 0)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <input type="submit" />').length, 0)
  assert.equal(fieldHits('fixture.tsx', 'export const View = () => <input aria-label="" />').length, 1)
  const linked = 'const id = "shot"\nexport const View = () => <><label htmlFor={id}>Note</label><textarea id={id} /></>'
  assert.equal(fieldHits('fixture.tsx', linked).length, 0)
})

test('form fields keep a label', () => {
  const budget = JSON.parse(readFileSync(new URL('./fieldLabelBudget.json', import.meta.url), 'utf8')) as Record<string, number>
  const problems = compareBudget(budget, scanFieldCounts(), 'fieldLabelBudget.json')
  assert.deepEqual(problems, [], problems.join('\n'))
})
