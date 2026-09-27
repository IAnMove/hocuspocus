import assert from 'node:assert/strict'
import test from 'node:test'
import { buildState, commitUrl, shortCommit } from '../src/lib/buildIdentity.ts'

const A = 'a'.repeat(40)
const B = 'b'.repeat(40)
const about = (backend: string, ui?: string) => ({ backend: { commit: backend, version: '0.9.0', started_at: '' }, ui: ui ? { commit: ui } : {} })

test('short commit only accepts hex hashes', () => {
  assert.equal(shortCommit(A), 'aaaaaaa')
  assert.equal(shortCommit('unknown'), '')
  assert.equal(shortCommit(undefined), '')
})

test('build state tells a stale tab from a stale build', () => {
  assert.equal(buildState(about(A, A), A), 'in-sync')
  assert.equal(buildState(about(A, A), B), 'reload')
  assert.equal(buildState(about(A, B), B), 'rebuild')
  assert.equal(buildState(about(A), ''), 'unknown')
  assert.equal(buildState(about(A), B), 'reload')
  assert.equal(buildState(about('unknown', A), A), 'unknown')
  assert.equal(buildState(null, A), 'unknown')
})

test('commit links point at the repository', () => {
  assert.equal(commitUrl('https://github.com/IAnMove/hocuspocus/', A), `https://github.com/IAnMove/hocuspocus/commit/${A}`)
  assert.equal(commitUrl('https://github.com/IAnMove/hocuspocus', 'unknown'), null)
})
