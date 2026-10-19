import assert from 'node:assert/strict'
import test from 'node:test'

import { INSTALLED_FIRST_DEFAULTS, installedPreferredModel } from '../src/lib/preferredModels.ts'

const flux = { model_type: 'flux2_klein_9b', is_downloaded: true }
const base = { model_type: 'qwen_image_21', is_downloaded: true }
const turbo = { model_type: 'qwen_image_21_turbo', is_downloaded: true }

test('image mode defaults to Qwen Image 2.1 Turbo once its weights are installed, even next to the base Qwen', () => {
  assert.equal(INSTALLED_FIRST_DEFAULTS.image[0], 'qwen_image_21_turbo')
  assert.equal(installedPreferredModel('image', [flux, turbo]), 'qwen_image_21_turbo')
  assert.equal(installedPreferredModel('image', [flux, base, turbo]), 'qwen_image_21_turbo')
  assert.equal(installedPreferredModel('image', [turbo, base, flux]), 'qwen_image_21_turbo')
})

test('an install with only the base Qwen Image 2.1 keeps it instead of falling back to another family', () => {
  assert.equal(installedPreferredModel('image', [flux, base]), 'qwen_image_21')
  assert.equal(installedPreferredModel('image', [flux, base, { ...turbo, is_downloaded: false }]), 'qwen_image_21')
})

test('a Qwen Image 2.1 that is only in the catalog does not become the default', () => {
  assert.equal(installedPreferredModel('image', [flux, { ...base, is_downloaded: false }, { ...turbo, is_downloaded: false }]), null)
  assert.equal(installedPreferredModel('image', [flux, { model_type: 'qwen_image_21' }, { model_type: 'qwen_image_21_turbo' }]), null)
  assert.equal(installedPreferredModel('image', [flux]), null)
})

test('other modes keep their own defaults', () => {
  const models = [base, turbo]
  assert.equal(installedPreferredModel('video', models), null)
  assert.equal(installedPreferredModel('audio', models), null)
})

test('audio mode still prefers VoxCPM2 once installed', () => {
  assert.equal(installedPreferredModel('audio', [{ model_type: 'voxcpm2_voicedesign', is_downloaded: true }]), 'voxcpm2_voicedesign')
  assert.equal(installedPreferredModel('audio', [{ model_type: 'kugelaudio_0_open', is_downloaded: true }]), null)
})
