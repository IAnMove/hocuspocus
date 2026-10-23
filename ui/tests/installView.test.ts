import assert from 'node:assert/strict'
import test from 'node:test'
import type { InstallComponent, InstallStatus } from '../src/api/installManager.ts'
import { SUCCESS_NOTICE_MS, exceedsFreeSpace, finishedNotice, reclaimLabel, rowActions, sizeLabel } from '../src/lib/installView.ts'

const GB = 1024 ** 3

function row(patch: Partial<InstallComponent> = {}): InstallComponent {
  return {
    id: 'sam', engine: 'sam', title: 'SAM', summary: '', estimatedBytes: 6 * GB, restartRequired: false,
    state: 'not_installed', supported: true, reason: null, sizeBytes: 0, reclaimableBytes: 0, job: null, ...patch,
  }
}

const idle: Pick<InstallStatus, 'busy' | 'launcher'> = { busy: null, launcher: { available: true, reason: null } }

test('a missing component can be installed, an installed one only removed, an outdated one both', () => {
  assert.deepEqual(rowActions(row(), idle), { primary: 'install', canUninstall: false, blockedBy: null })
  assert.deepEqual(rowActions(row({ state: 'installed' }), idle), { primary: null, canUninstall: true, blockedBy: null })
  assert.deepEqual(rowActions(row({ state: 'needs_update' }), idle), { primary: 'update', canUninstall: true, blockedBy: null })
})

test('unsupported and running components offer nothing', () => {
  for (const state of ['unsupported', 'running'] as const) {
    assert.deepEqual(rowActions(row({ state }), idle), { primary: null, canUninstall: false, blockedBy: null })
  }
})

test('one change at a time: everything else waits while something runs', () => {
  const busy = { ...idle, busy: 'hunyuan3d' }
  assert.equal(rowActions(row(), busy).blockedBy, 'busy')
  assert.equal(rowActions(row({ state: 'installed' }), busy).blockedBy, 'busy')
})

test('without Pinokio only installing is blocked; removing needs no launcher', () => {
  const offline = { busy: null, launcher: { available: false, reason: 'not_in_pinokio' as const } }
  assert.equal(rowActions(row(), offline).blockedBy, 'launcher')
  assert.equal(rowActions(row({ state: 'needs_update' }), offline).blockedBy, 'launcher')
  assert.equal(rowActions(row({ state: 'installed' }), offline).blockedBy, null)
})

test('size shows the estimate before installing, the measurement after, and says when it is still counting', () => {
  assert.deepEqual(sizeLabel(row()), { bytes: 6 * GB, kind: 'estimated' })
  assert.deepEqual(sizeLabel(row({ state: 'unsupported' })), { bytes: 6 * GB, kind: 'estimated' })
  assert.deepEqual(sizeLabel(row({ state: 'installed', sizeBytes: 5 * GB })), { bytes: 5 * GB, kind: 'measured' })
  assert.deepEqual(sizeLabel(row({ state: 'installed', sizeBytes: null })), { bytes: null, kind: 'measuring' })
})

test('removal says what it really frees, and when uv shared most of the folder with Pinokio\'s cache', () => {
  assert.equal(reclaimLabel(row()), null, 'nothing to free before it is installed')
  assert.deepEqual(reclaimLabel(row({ state: 'installed', sizeBytes: 7 * GB, reclaimableBytes: 0.3 * GB })), { bytes: 0.3 * GB, mostlyShared: true })
  assert.deepEqual(reclaimLabel(row({ state: 'needs_update', sizeBytes: 7 * GB, reclaimableBytes: 6 * GB })), { bytes: 6 * GB, mostlyShared: false })
  assert.deepEqual(reclaimLabel(row({ state: 'installed', sizeBytes: 7 * GB, reclaimableBytes: null })), { bytes: null, mostlyShared: false })
})

test('the low-space warning only applies to something that still has to be downloaded', () => {
  assert.equal(exceedsFreeSpace(row(), 5 * GB), true)
  assert.equal(exceedsFreeSpace(row(), 7 * GB), false)
  assert.equal(exceedsFreeSpace(row({ state: 'installed' }), 1), false)
})

test('a finished job is reported once the component is idle', () => {
  const job = { component: 'sam', startedAt: 1, finishedAt: 2, code: null, message: null }
  assert.equal(finishedNotice(row()), null)
  assert.equal(finishedNotice(row({ job: { ...job, kind: 'install', state: 'running' } })), null)
  assert.equal(finishedNotice(row({ job: { ...job, kind: 'install', state: 'succeeded' } }), 2500), 'installed')
  assert.equal(finishedNotice(row({ job: { ...job, kind: 'uninstall', state: 'succeeded' } }), 2500), 'removed')
  assert.equal(finishedNotice(row({ job: { ...job, kind: 'install', state: 'failed', code: 'interrupted' } })), 'failed')
})

test('a success fades after half an hour; a failure stays until the next attempt', () => {
  const finished = { component: 'sam', startedAt: 1, finishedAt: 1000, code: null, message: null }
  const later = 1000 * 1000 + SUCCESS_NOTICE_MS + 1
  const fresh = 1000 * 1000 + 1000
  assert.equal(finishedNotice(row({ job: { ...finished, kind: 'install', state: 'succeeded' } }), fresh), 'installed')
  assert.equal(finishedNotice(row({ job: { ...finished, kind: 'install', state: 'succeeded' } }), later), null)
  assert.equal(finishedNotice(row({ job: { ...finished, kind: 'uninstall', state: 'succeeded' } }), later), null)
  assert.equal(finishedNotice(row({ job: { ...finished, kind: 'install', state: 'failed', code: 'interrupted' } }), later), 'failed')
})
