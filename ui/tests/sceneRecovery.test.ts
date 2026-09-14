import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { SceneHandoffRecovery, releaseStoredSceneCopy } from '../src/lib/sceneRecovery'

test('a long native batch retains unsaved work without accumulating saved scenes', () => {
  const storage = new JSDOM('', { url: 'http://localhost', storageQuota: 1_000_000 }).window.sessionStorage
  const recovery = new SceneHandoffRecovery()
  const original = { name: 'Unsaved user scene', data: 'u'.repeat(200_000) }
  recovery.backup(storage, 'default', original)
  storage.setItem('unrelated', 'keep me')
  for (let index = 0; index < 60; index++) {
    const scene = { name: `Shot ${index}`, data: 's'.repeat(200_000) }
    const key = `hocuspocus:series-scene:default:series:episode:${index}`
    const copy = JSON.stringify(scene)
    storage.setItem(key, copy)
    recovery.markSaved('default', scene)
    releaseStoredSceneCopy(storage, key, copy)
    recovery.backup(storage, 'default', structuredClone(scene))
  }
  assert.equal(storage.length, 2)
  assert.equal(storage.getItem('unrelated'), 'keep me')
  assert.ok(Object.keys(storage).some(key => storage.getItem(key) === JSON.stringify(original)))
})

test('edits after saving, a different workspace and an unsaved failed render still get backups', () => {
  const storage = new JSDOM('', { url: 'http://localhost' }).window.sessionStorage
  const recovery = new SceneHandoffRecovery()
  const scene = { name: 'Saved shot', mouth: 'closed' }
  recovery.markSaved('default', scene)
  recovery.backup(storage, 'default', { ...scene, mouth: 'wide' })
  recovery.backup(storage, 'other', scene)
  recovery.backup(storage, 'default', { name: 'Failed save' })
  assert.equal(storage.length, 3)
})

test('releasing a completed take cannot delete a newer draft stored under the same shot key', () => {
  const storage = new JSDOM('', { url: 'http://localhost' }).window.sessionStorage
  storage.setItem('shot', 'newer draft')
  releaseStoredSceneCopy(storage, 'shot', 'rendered scene')
  assert.equal(storage.getItem('shot'), 'newer draft')
})
