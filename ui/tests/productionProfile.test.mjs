import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applySeriesGlobalProvider,
  DEFAULT_PRODUCTION_PROFILE,
  resolveSupportedVideoFormat,
  seriesProviderFieldsFromProfile,
  seriesProviderMatchesGlobal,
} from '../src/lib/productionProfile.ts'

const options = {
  resolution_preset_order: ['480p', '540p', '720p', '768p'],
  resolution_presets: {
    '480p': { values: { '16:9': '864x480', '9:16': '480x864' } },
    '540p': { values: { '16:9': '960x544', '9:16': '544x960' } },
    '720p': { values: { '16:9': '1280x704', '9:16': '704x1280' } },
    '768p': { values: { '16:9': '1344x768', '9:16': '768x1344' } },
  },
  supports_auto_aspect: false,
}

test('new production profiles prefer local Qwen Image 2.1', () => {
  assert.deepEqual(DEFAULT_PRODUCTION_PROFILE.image, { provider: 'local', model: 'qwen_image_21' })
  const fields = seriesProviderFieldsFromProfile(DEFAULT_PRODUCTION_PROFILE)
  assert.equal(fields.imageProvider, 'maestro')
  assert.equal(fields.imageModel, 'qwen_image_21')
})

test('keeps an exact H3 Legacy tier and portrait orientation', () => {
  assert.deepEqual(resolveSupportedVideoFormat(options, '768p', '9:16'), {
    resolution: '768p',
    aspectRatio: '9:16',
    adjusted: false,
  })
})

test('series global profile compares every copied field including shifts', () => {
  const fields = seriesProviderFieldsFromProfile({
    ...DEFAULT_PRODUCTION_PROFILE,
    video: {
      ...DEFAULT_PRODUCTION_PROFILE.video,
      model: 'minimax_h3_fused_turbo',
      settings: {
        ...DEFAULT_PRODUCTION_PROFILE.video.settings,
        steps: 4,
        flowShift: 7,
        audioShift: 1,
        profile: 'fast',
      },
    },
  })
  const provider = applySeriesGlobalProvider({
    useGlobalProfile: true,
    writingProvider: 'minimax',
    writingModel: 'old',
    writingBaseUrl: '',
    imageProvider: 'maestro',
    imageModel: '',
    videoModel: 'minimax_h3',
    videoSettings: { resolution: '540p', orientation: 'landscape', numInferenceSteps: 20, flowShift: 12, audioShift: 3, modelProfile: 'quality' },
  }, fields)
  assert.equal(provider.videoModel, 'minimax_h3_fused_turbo')
  assert.equal(provider.videoSettings.flowShift, 7)
  assert.equal(provider.videoSettings.audioShift, 1)
  assert.equal(provider.videoSettings.modelProfile, 'fast')
  assert.equal(provider.writingBaseUrl, 'https://api.minimax.io')
  assert.equal(seriesProviderMatchesGlobal(provider, fields), true)
  assert.equal(seriesProviderMatchesGlobal({
    ...provider,
    videoSettings: { ...provider.videoSettings, flowShift: 12 },
  }, fields), false)
})

test('chooses the nearest advertised tier without flipping orientation', () => {
  assert.deepEqual(resolveSupportedVideoFormat(options, '1080p', '9:16'), {
    resolution: '768p',
    aspectRatio: '9:16',
    adjusted: true,
  })
})
