import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { canonicalClientTaskId, fetchRecipes } from '../src/api/client.ts'

const clientPath = fileURLToPath(new URL('../src/api/client.ts', import.meta.url))
const readmePath = fileURLToPath(new URL('../README.md', import.meta.url))

test('client.ts remains the public HTTP facade and reexports slice modules', () => {
  const source = readFileSync(clientPath, 'utf8')
  assert.match(source, /export \* from '\.\/generation'/)
  assert.match(source, /export \* from '\.\/stories'/)
  assert.match(source, /export \* from '\.\/director'/)
  assert.equal(typeof canonicalClientTaskId, 'function')
  assert.equal(typeof fetchRecipes, 'function')
})

test('ui README keeps the src/api/client.ts literal', () => {
  assert.match(readFileSync(readmePath, 'utf8'), /src\/api\/client\.ts/)
})
