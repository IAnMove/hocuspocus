import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createStoryProject,
  normalizeStoryProject,
} from '../src/features/stories/model.ts'
import { resolveSupportedVideoFormat } from '../src/lib/productionProfile.ts'

const h3Options = {
  resolution_preset_order: ['480p', '540p', '720p', '768p'],
  resolution_presets: {
    '480p': { values: { '16:9': '864x480', '9:16': '480x864' } },
    '540p': { values: { '16:9': '960x544', '9:16': '544x960' } },
    '720p': { values: { '16:9': '1280x704', '9:16': '704x1280' } },
    '768p': { values: { '16:9': '1344x768', '9:16': '768x1344' } },
  },
  supports_auto_aspect: false,
}

test('new Stories inherit the global profile with a dormant H3 override', () => {
  const project = createStoryProject('music_video')

  assert.equal(project.provider.useGlobalProfile, true)
  assert.deepEqual(project.videoOverride, {
    model: 'minimax_h3_legacy',
    resolution: '540p',
    aspectRatio: '16:9',
  })
})

test('legacy override projects retain a capture sentinel instead of changing model silently', () => {
  const legacy = structuredClone(createStoryProject())
  legacy.provider.useGlobalProfile = false
  delete legacy.videoOverride

  assert.deepEqual(normalizeStoryProject(legacy).videoOverride, {
    model: '',
    resolution: 'auto',
    aspectRatio: 'auto',
  })
})

test('an explicit Story recipe survives normalization and resolves to the nearest H3 tier', () => {
  const saved = createStoryProject()
  saved.provider.useGlobalProfile = false
  saved.videoOverride = {
    model: 'minimax_h3_legacy',
    resolution: '1080p',
    aspectRatio: '9:16',
  }

  const normalized = normalizeStoryProject(saved)
  assert.deepEqual(normalized.videoOverride, saved.videoOverride)
  assert.deepEqual(resolveSupportedVideoFormat(
    h3Options,
    normalized.videoOverride.resolution,
    normalized.videoOverride.aspectRatio,
  ), {
    resolution: '768p',
    aspectRatio: '9:16',
    adjusted: true,
  })
})
