import assert from 'node:assert/strict'
import test from 'node:test'

import { installedPreferredModel } from '../src/lib/preferredModels.ts'

const flux = { model_type: 'flux2_klein_9b', is_downloaded: true }

test('image mode defaults to Qwen Image 2.1 once its weights are installed', () => {
  const models = [flux, { model_type: 'qwen_image_21', is_downloaded: true }]
  assert.equal(installedPreferredModel('image', models), 'qwen_image_21')
})

test('a Qwen Image 2.1 that is only in the catalog does not become the default', () => {
  assert.equal(installedPreferredModel('image', [flux, { model_type: 'qwen_image_21', is_downloaded: false }]), null)
  assert.equal(installedPreferredModel('image', [flux, { model_type: 'qwen_image_21' }]), null)
  assert.equal(installedPreferredModel('image', [flux]), null)
})

test('other modes keep their own defaults', () => {
  const models = [{ model_type: 'qwen_image_21', is_downloaded: true }]
  assert.equal(installedPreferredModel('video', models), null)
  assert.equal(installedPreferredModel('audio', models), null)
})
